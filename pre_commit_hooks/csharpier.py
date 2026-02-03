from __future__ import annotations

import argparse
import os
import subprocess
import json
import sys
from typing import Any, Sequence
import re
import logging

class CalledProcessError(RuntimeError):
  def __init__(
          self,
          cmd: tuple[str, ...],
          expected_code: int,
          return_code: int,
          stdout: bytes,
          stderr: bytes | None,
  ) -> None:
    super().__init__(cmd, expected_code, return_code, stdout, stderr)
    self.cmd = cmd
    self.expected_code = expected_code
    self.return_code = return_code
    self.stdout = stdout
    self.stderr = stderr

  def __bytes__(self) -> bytes:
    def _indent_or_none(part: bytes | None) -> bytes:
      if part:
        return b'\n    ' + part.replace(b'\n', b'\n    ').rstrip()
      else:
        return b' (none)'

    return b''.join((
      f'command: {self.cmd!r}\n'.encode(),
      f'expected code: {self.expected_code}\n'.encode(),
      f'return code: {self.return_code}\n'.encode(),
      b'stdout:', _indent_or_none(self.stdout), b'\n',
      b'stderr:', _indent_or_none(self.stderr),
    ))

  def __str__(self) -> str:
    return self.__bytes__().decode()


def cmd_output(*cmd: str, retcode: int | None = 0, **kwargs: Any) -> str:
  """Run an external program and return what it wrote on the stdout.

  Args:
      *cmd (str): Command and arguments to run.
      retcode (int | None, optional): Raise CalledProcessError if the return code is different from this value. Defaults to 0.
      **kwargs (Any): Additional arguments to Popen.

  Raises:
      CalledProcessError: If the return code is different from the expected retcode.

  Returns:
      str: The standard output of the command.
  """
  logging.debug(f'Running command: {cmd} with kwargs: {kwargs}')

  kwargs.setdefault('stdout', subprocess.PIPE)
  kwargs.setdefault('stderr', subprocess.PIPE)
  proc = subprocess.Popen(cmd, **kwargs)
  stdout, stderr = proc.communicate()
  stdout = stdout.decode()
  if retcode is not None and proc.returncode != retcode:
    raise CalledProcessError(cmd, retcode, proc.returncode, stdout, stderr)
  return stdout


def _get_container_id() -> str:
  """Get the identifier of the Docker container we are running inside.

  Raises:
      RuntimeError: If the container ID cannot be found in /proc/1/cgroup.

  Returns:
      str: The Docker container ID.
  """

  # It's assumed that we already check /proc/1/cgroup in _is_in_docker. The
  # cpuset cgroup controller existed since cgroups were introduced so this
  # way of getting the container ID is pretty reliable.
  with open('/proc/1/cgroup', 'rb') as f:
    for line in f.readlines():
      if line.split(b':')[1] == b'cpuset':
        return os.path.basename(line.split(b':')[2]).strip().decode()
  raise RuntimeError('Failed to find the container ID in /proc/1/cgroup.')


def _is_in_docker() -> bool:
  """Check if the current environment is inside a Docker container.

  Returns:
      bool: True if running inside Docker, False otherwise.
  """
  try:
    with open('/proc/1/cgroup', 'rb') as f:
      return b'docker' in f.read()
  except FileNotFoundError:
    return False


def _get_docker_path(path: str) -> str:
  """Map a host path to the equivalent path inside the Docker container.
  Args:
      path (str): The host path to map.
  Returns:
      str: The equivalent path inside the Docker container.
  """
  if not _is_in_docker():
    return path

  container_id = _get_container_id()

  try:
    out = cmd_output('docker', 'inspect', container_id)
  except CalledProcessError:
    # self-container was not visible from here (perhaps docker-in-docker)
    return path

  container, = json.loads(out)
  for mount in container['Mounts']:
    src_path = mount['Source']
    to_path = mount['Destination']
    if os.path.commonpath((path, to_path)) == to_path:
      # So there is something in common,
      # and we can proceed remapping it
      return path.replace(to_path, src_path)
  # we're in Docker, but the path is not mounted, cannot really do anything,
  # so fall back to original path
  return path


def get_docker_user() -> tuple[str, ...]:  # pragma: win32 no cover
  """Get the Docker user argument to map the current user inside the container.
  Returns:
      tuple[str, ...]: The Docker user argument.
  """
  try:
    return ('-u', f'{os.getuid()}:{os.getgid()}')
  except AttributeError:
    return ()


def run_command(argv: Sequence[str]) -> bool:
  """Run an external command and relay its output.

  When the command runs successfully, its stdout is printed. When it fails,
  its stderr and stdout are printed.

  Args:
      argv (Sequence[str]): The command and its arguments to run.
  Returns:
      bool: True if the command ran successfully, False otherwise.
  """
  try:
    out = cmd_output(*argv)
    if out:
      print(out)
    return True
  except CalledProcessError as e:
    if e.stderr:
      print(e.stderr, file=sys.stderr)
    if e.stdout:
      print(e.stdout)
  except FileNotFoundError:
    logging.warning(f'{argv[0]} not found!')
  return False


def setup_dotnet_environment() -> None:
  """Setup environment variables for dotnet commands.

  On Windows, DOTNET_ROOT is usually set by the installer. On Unix-like
  systems, we try to find the dotnet executable and set DOTNET_ROOT to its
  directory if not already set.
  """
  # Prevent telemetry and dotnet preamble
  if 'DOTNET_CLI_TELEMETRY_OPTOUT' not in os.environ:
    os.environ['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
  if 'DOTNET_NOLOGO' not in os.environ:
    os.environ['DOTNET_NOLOGO'] = '1'

  if 'DOTNET_ROOT' not in os.environ:
    dotnet = find_executable('dotnet')
    if dotnet:
      if os.name != 'nt':  # Unix-like systems
        os.environ['DOTNET_ROOT'] = os.path.dirname(dotnet)
        logging.debug(f'Set DOTNET_ROOT to {os.environ["DOTNET_ROOT"]}')


def run_dotnet_command(argv: Sequence[str]) -> bool:
  """Run a dotnet command with the appropriate environment setup.

  Args:
      argv (Sequence[str]): The command and its arguments to run.
  Returns:
      bool: True if the command ran successfully, False otherwise.
  """
  setup_dotnet_environment()
  # Then run the command passed in argv
  return run_command(argv)

def split_path(path: str) -> list[str]:
  """Split a PATH-like environment variable into its components.

  Args:
      path (str): The PATH-like environment variable to split.
  Returns:
      list[str]: The components of the PATH-like variable.
  """
  if path == '':
    return []
  if path.find(os.pathsep) == -1:
    return [path]
  return path.split(os.pathsep)


def enumerate_executables(exe: str, path: str | None = None, insert: str | None = None, flag: int = os.X_OK) -> list[str]:
  """Enumerate all instances of an executable using a PATH-like variable.
  
  This is aware of the (Windows) PATHEXT environment variable, and will
  automatically search an equivalent .exe (on all OSes, so this can be run from
  WSL). When an insert path is specified, that path will be searched first. When
  path is None, no PATH-like searching will be done, only the insert path (if
  specified) will be searched. The flag parameter specifies the access mode to
  check for.

  Args:
      exe (str): The name of the executable to search for.
      path (str | None, optional): The PATH-like specification. Defaults to None.
      insert (str | None, optional): A path to insert at the start of the search. Defaults to None.
      flag (int, optional): The access mode to check for. Defaults to os.X_OK.
  Returns:
      list[str]: A list of paths to the found executables.
  """
  exe = os.path.normpath(exe)
  executables = []
  if 'PATHEXT' in os.environ:
    exts = split_path(os.environ['PATHEXT'])
    possible_exe_names = tuple(f'{exe}{ext}' for ext in exts) + (exe,)
  else:
    # Also try with .exe anyway, for WSL setups
    possible_exe_names = (exe, exe+'.exe')

  # When an insert path is specified, look there first
  if path is not None:
    path_dirs = split_path(path)
  else:
    path_dirs = []
  if insert:
    candidates = [insert] + path_dirs
  else:
    candidates = path_dirs

  for dir in candidates:
    for possible_exe_name in possible_exe_names:
      joined = os.path.join(dir, possible_exe_name)
      if os.path.isfile(joined) and os.access(joined, flag):
        resolved_path = os.path.realpath(joined)
        if resolved_path not in executables:
          logging.debug(f'Found {exe} as {resolved_path}')
          executables.append(resolved_path)
  
  return executables


def find_executable(exe: str) -> str | None:
  """Find an executable in the PATH.

  This is aware of the (Windows) PATHEXT environment variable, and will
  automatically search an equivalent .exe (on all OSes, so this can be run from
  WSL).

  Args:
      exe (str): The name of the executable to find.
  Returns:
      str | None: The path to the found executable, or None if not found.
  """
  executables = enumerate_executables(exe=exe, path=os.environ.get('PATH'))
  if executables:
    return executables[0]
  return None


def docker_csharpier_version(docker: str, image: str) -> str | None:
  """Get the version of CSharpier in a Docker image.

  This actively runs the Docker image with the --version argument and parses
  the output.

  Args:
      docker (str): The path to the Docker executable.
      image (str): The Docker image to inspect.
  Returns:
      str | None: The version of CSharpier in the Docker image, or None if it cannot be determined.
  """
  try:
    out = cmd_output(docker, 'run', '--rm', image, '--version')
    return get_semver(out.strip())
  except CalledProcessError:
    return None


def run_docker(version: str | None, image: str, argv: Sequence[str] | None = None) -> bool:
  """Run CSharpier as a Docker container.
  The current path will be mounted rw at /src inside the container and the
  current user and group ids will be mapped into the container.
  Args:
      version (str | None): The version of CSharpier to use. If None, the latest version is used.
      image (str): The Docker image to use.
      argv (Sequence[str] | None, optional): The arguments to pass to CSharpier inside the container. Defaults to None.
  Returns:
      bool: True if the Docker container ran successfully, False otherwise.
  """
  # Adapt image specification to contain version
  request_version = False
  if version:
    if re.search(':[a-z0-9]+(?:[._-][a-z0-9]+)*$', image):
      logging.warning(f'Provided image {image} already contains a tag. Will not override with {version}')
      request_version = True
    else:
      image = image + ':' + version
  else:
    request_version = True

  # Find docker executable, cannot run without it
  docker = find_executable('docker')
  if not docker:
    logging.warning('docker cannot be found in PATH!')
    return False
  
  if request_version:
    version = docker_csharpier_version(docker, image)

  if not version:
    logging.error(f'Could not determine csharpier version in Docker image {image}!')
    return False

  run = [ 'docker', 'run',
            '--rm',
            *get_docker_user(),
            '-v', f'{_get_docker_path(os.getcwd())}:/src:rw,Z',
            '-w', '/src',
            '-t',
            image ]
  if is_version_greater_or_equal(version, '1.0.0'):
    run += ['format']
  if argv:
    run += argv
  result = run_command(argv=run)
  if result:
    logging.info(f'Ran Docker container based on {image} with {" ".join(argv if argv else [])}')
  else:
    logging.error(f'Cannot create Docker container from "{image}". Consider the --install option.')
  return result


def make_executable(path: str):
  """Make a file executable by setting its x bits based on its r bits.
  Args:
      path (str): The path to the file to make executable.
  """
  mode = os.stat(path).st_mode
  mode |= (mode & 0o444) >> 2    # copy R bits to X
  os.chmod(path, mode)


def dotnet_default_root() -> str | None:
  """Get the default root directory for dotnet tools.

  Returns:
      str | None: The default root directory for dotnet tools, or None if it cannot be determined.
  """
  # dotnet tools installs globally under USERPROFILE on Windows and HOME
  # elsewhere
  home = os.environ.get('USERPROFILE', os.environ.get('HOME'))
  if not home:
    return None

  # Hidden dotnet directory
  root = os.path.join(home, '.dotnet')
  return root


def install_tooldir(version: str | None = None) -> str | None:
  """Decide the installation directory for the csharpier dotnet tool.

  When version is None, the global installation directory is returned. When
  version is specified, a version-specific directory is returned.

  Args:
      version (str | None): The version of csharpier to install.
  Returns:
      str | None: The installation directory for csharpier, or None if it cannot be determined.
  """
  root = dotnet_default_root()
  if root:
    if version:
      return os.path.join(root, 'pre-commit', 'csharpier', version)
    else:
      return os.path.join(root, 'tools')

  return None


def install_csharpier(version: str | None = None) -> str | None:
  """Install csharpier as a dotnet tool.

  When version is None, the latest version of csharpier is installed globally.
  When version is specified, that specific version is installed under a version-
  specific directory. This is to allow multiple versions to coexist and have a
  version pinned and under the control of pre-commit.
  
  Args:
      version (str | None): The version of csharpier to install.
  Returns:
      str | None: The path to the installed csharpier executable, or None if
      installation failed.
  """
  target = install_tooldir(version)
  if not target:
    logging.critical('Could not determine target directory for csharpier installation!')
    return None

  if not os.path.exists(target):
    os.makedirs(target)

  # Find dotnet executable, cannot run without it
  dotnet = find_executable('dotnet')
  if not dotnet:
    logging.critical('dotnet cannot be found in PATH!')
    return None

  if version:
    # Version is specified, install the specific version of csharpier under the
    # same root directory as other dotnet stuff, but using a different hierarchy
    # since we will need to be able to point to that specific version/location
    # when running.
    install = [ dotnet, 'tool', 'install', 'csharpier',
                  '--tool-path', target,
                  '--version', version ]
  else:
    # No version specified, install the latest version of csharpier, globally
    install = [ dotnet, 'tool', 'install', '-g', 'csharpier' ]

  if run_dotnet_command(install):
    binaries = ['dotnet-csharpier', 'csharpier']
    for binary in binaries:
      executables = enumerate_executables(exe=binary, path=None, flag=os.R_OK, insert=target)
      if executables:
        csharpier = executables[0]
        make_executable(csharpier)
        logging.info(f'Installed csharpier as {csharpier}')
        return csharpier
  else:
    logging.error('Failed to install csharpier!')

  return None


def is_version_greater_or_equal(version1: str, version2: str) -> bool:
  """Compare two semantic version strings.
  Args:
      version1 (str): The first version string.
      version2 (str): The second version string.
  Returns:
      bool: True if version1 >= version2, False otherwise.
  """
  v1_parts = [int(x) for x in version1.split('.')]
  v2_parts = [int(x) for x in version2.split('.')]
  
  # Pad the shorter version with zeros
  max_len = max(len(v1_parts), len(v2_parts))
  v1_parts += [0] * (max_len - len(v1_parts))
  v2_parts += [0] * (max_len - len(v2_parts))
  
  # Compare each part
  for i in range(max_len):
    if v1_parts[i] > v2_parts[i]:
      return True
    elif v1_parts[i] < v2_parts[i]:
      return False
  
  # Versions are equal
  return True


def get_semver(version: str) -> str | None:
  """Extract the semantic version from a version string.
  Args:
      version (str): The version string to extract from.
  Returns:
      str | None: The extracted semantic version, or None if not found.
  """
  match = re.search(r'(\d+(?:\.\d+){0,2})', version)
  if match:
    return match.group(1)
  return None


def csharpier_version(bin: Sequence[str]) -> str | None:
  """Get the semantic version of the csharpier executable.
  Args:
      bin (Sequence[str]): The command to run csharpier.
  Returns:
      str | None: The semantic version string, or None if it cannot be determined.
  """
  setup_dotnet_environment()
  try:
    command = bin + ['--version']
    return get_semver(cmd_output(*command).strip())
  except CalledProcessError:
    return None


def run_csharpier(bin: Sequence[str], argv: Sequence[str] | None = None, version: str | None = None) -> bool:
  """Run csharpier directly.
  Args:
      bin (Sequence[str]): The command to run csharpier.
      argv (Sequence[str] | None, optional): The arguments to pass to csharpier. Defaults to None.
      version (str | None, optional): The version of csharpier to use. Defaults to None.
  Returns:
      bool: True if csharpier ran successfully, False otherwise.
  """
  if not version:
    version = csharpier_version(bin)
    if not version:
      logging.error('Could not determine csharpier version!')
      return False

  if is_version_greater_or_equal(version, '1.0.0'):
    bin = bin + ['format']
  csharpier = ' '.join(bin)
  result = run_dotnet_command(bin + (argv or []))
  if result:
    logging.info(f'Ran {csharpier} directly with {" ".join(argv or [])}')
  else:
    logging.error(f'"{csharpier}" cannot be run. Install csharpier manually or consider the --install option.')
  return result


def run_csharpier_as_binary(version: str | None, path: str | None = None, argv: Sequence[str] | None = None) -> bool:
  """Run csharpier as a direct binary.

  Args:
      version (str | None): The version of csharpier to use. If None, any version is accepted.
      path (str | None, optional): a PATH-like searching directive. Defaults to None.
      argv (Sequence[str] | None, optional): The arguments to pass to csharpier. Defaults to None.
  Returns:
      bool: True if csharpier ran successfully, False otherwise.
  """
  default_dir = install_tooldir(version)

  # List of possible binary names: name changed from dotnet-csharpier to
  # simply csharpier in version 1.0.0, so we will try both.
  binaries = ['dotnet-csharpier', 'csharpier']
  for binary in binaries:
    for exe in enumerate_executables(exe=binary, path=path, insert=default_dir):
      csharpier = [ exe ]
      installed_version = csharpier_version(csharpier)
      if not installed_version:
        continue
      if version:
        if installed_version == version:
          return run_csharpier(csharpier, argv, version)
      else:
        return run_csharpier(csharpier, argv, installed_version)
  return False


def run_csharpier_as_local_tool(version: str | None, argv: Sequence[str] | None = None) -> bool:
  """Run csharpier as a dotnet local tool.

  Note that, as per the dotnet documentation, this cannot run global tools.

  Args:
      version (str | None): The version of csharpier to use. If None, any version is accepted.
      argv (Sequence[str] | None, optional): The arguments to pass to csharpier. Defaults to None.
  Returns:
      bool: True if csharpier ran successfully, False otherwise.
  """
  # Find dotnet executable, cannot run without it
  dotnet = find_executable('dotnet')
  if not dotnet:
    return False

  # Trying to find csharpier as a local tool, so we construct a command that
  # will run it via dotnet. This is the way and the equivalent of dotnet tool
  # run csharpier.
  csharpier = [ dotnet, 'csharpier' ]

  # Check its version, if we can't, then there isn't a local tool installed
  installed_version = csharpier_version(csharpier)
  if not installed_version:
    return False

  # Check version match when relevant, otherwise run it at the found version
  # since version was irrelevant.
  if version:
    if installed_version == version:
      return run_csharpier(csharpier, argv, version)
  else:
    return run_csharpier(csharpier, argv, installed_version)

  return False


def run_csharpier_as_tool(version: str | None, argv: Sequence[str] | None = None) -> bool:
  """Run csharpier as a dotnet tool (local or global).
  Args:
      version (str | None): The version of csharpier to use. If None, any version is accepted.
      argv (Sequence[str] | None, optional): The arguments to pass to csharpier. Defaults to None.
  Returns:
      bool: True if csharpier ran successfully, False otherwise.
  """
  # Run as a local tool first, if not found, try running as a binary from where
  # dotnet installs the global tools.
  if run_csharpier_as_local_tool(version, argv=argv):
    return True
  return run_csharpier_as_binary(version, path=install_tooldir(), argv=argv)


def main(argv: Sequence[str] | None = None) -> int:
  argv = argv if argv is not None else sys.argv[1:]
  parser = argparse.ArgumentParser(prog='csharpier', description='(Install) and Run csharpier on files')

  # Parse arguments
  parser.add_argument(
    '-v', '--version',
    help='Force a specific version of csharpier to be used.'
  )
  # List of methods to find csharpier, and in which order.
  # bin: as a direct binary available under the path (or installed, see below)
  # tool: as a dotnet tool available under the path (or installed, see below)
  # docker: as a docker image.
  parser.add_argument(
    '-s', '--search',
    dest='methods',
    default='tool bin docker',
    help='Methods to find csharpier, and in which order. Space separated tokens: tool, bin or docker'
  )
  # When to install csharpier
  # never: Never install csharpier
  # version: Only install csharpier when a version is specified
  # always: Always install (as a global tool).
  parser.add_argument(
    '-i', '--install',
    dest='install',
    choices=['never', 'version', 'always'],
    default='version',
    help='When to install csharpier.'
  )
  parser.add_argument(
    '-d', '--docker',
    dest='image',
    default='ghcr.io/gpsgate/csharpier',
    help='Fully-qualified docker image to use.'
  )
  parser.add_argument(
    '-l', '--log-level', '--log',
    choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
    dest='loglevel',
    default='INFO',
    help='Debug level.'
  )
  parser.add_argument('args', nargs='*', help='Blind arguments to csharpier')
  args = parser.parse_args(argv)

  # Existing environment variables, if set, will have precedence.
  version = os.environ.get('PRE_COMMIT_HOOK_CSHARPIER_VERSION', args.version)
  if version:
    version = get_semver(version)
  methods = os.environ.get('PRE_COMMIT_HOOK_CSHARPIER_SEARCH', args.methods).lower().split()
  install = os.environ.get('PRE_COMMIT_HOOK_CSHARPIER_INSTALL', args.install).lower()
  image = os.environ.get('PRE_COMMIT_HOOK_CSHARPIER_DOCKER', args.image)
  loglevel = os.environ.get('PRE_COMMIT_HOOK_CSHARPIER_LOG_LEVEL', args.loglevel).upper()

  # Setup logging
  numeric_level = getattr(logging, loglevel.upper(), None)
  if not isinstance(numeric_level, int):
    raise ValueError('Invalid log level: %s' % loglevel)
  logging.basicConfig(level=numeric_level,
                      format='[csharpier-hook] [%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s',
                      datefmt='%Y%m%d %H%M%S')

  logging.debug(f'version: {version}, install: {install}, methods: {methods}, image: {image}')

  # First try the local methods in order
  for m in methods:
    if m == 'tool':
      logging.debug('Attempting to run csharpier as a dotnet tool...')
      if run_csharpier_as_tool(version, argv=args.args):
        return 0
    if m == 'bin':
      logging.debug('Attempting to run csharpier as a direct binary...')
      if run_csharpier_as_binary(version, path=os.environ.get('PATH'), argv=args.args):
        return 0

  # Still not found, try to install if allowed
  if (version and (install == 'always' or install == 'version')) or (not version and install == 'always'):
    logging.debug('Could not find csharpier locally, attempting to install it...')
    csharpier = install_csharpier(version)
    if csharpier:
      # Run it as the installed tool. This ensure that we will be able to find
      # it again next time.
      if run_csharpier_as_tool(version, argv=args.args):
        return 0
  
  if 'docker' in methods:
    logging.debug('Could not find csharpier locally, attempting to run it as a Docker container...')
    if run_docker(image=image, version=version, argv=args.args):
      return 0

  return 1

if __name__ == '__main__':
  raise SystemExit(main())