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


# Run an external program and return what it wrote on the stdout.
def cmd_output(*cmd: str, retcode: int | None = 0, **kwargs: Any) -> str:
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
  # It's assumed that we already check /proc/1/cgroup in _is_in_docker. The
  # cpuset cgroup controller existed since cgroups were introduced so this
  # way of getting the container ID is pretty reliable.
  with open('/proc/1/cgroup', 'rb') as f:
    for line in f.readlines():
      if line.split(b':')[1] == b'cpuset':
        return os.path.basename(line.split(b':')[2]).strip().decode()
  raise RuntimeError('Failed to find the container ID in /proc/1/cgroup.')


def _is_in_docker() -> bool:
  try:
    with open('/proc/1/cgroup', 'rb') as f:
      return b'docker' in f.read()
  except FileNotFoundError:
    return False


def _get_docker_path(path: str) -> str:
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
  try:
    return ('-u', f'{os.getuid()}:{os.getgid()}')
  except AttributeError:
    return ()


# Run an external program and relays its result(s) (stdout, stderr). stderr is
# relayed only when the program exited with an error.
def run_command(argv: Sequence[str]) -> bool:
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
  setup_dotnet_environment()
  # Then run the command passed in argv
  return run_command(argv)


# Enumerate all instances of an executable in the PATH. This is aware of the
# (Windows) PATHEXT environment variable, and will automatically search an
# equivalent .exe (on all OSes, so this can be run from WSL). When an insert
# path is specified, that path will be searched first. When envvar is None,
# no PATH-like searching will be done, only the insert path (if specified) will
# be searched. The flag parameter specifies the access mode to check for.
def enumerate_executables(exe: str, envvar: str | None = 'PATH', insert: str | None = None, flag: int = os.X_OK) -> Sequence[str]:
  exe = os.path.normpath(exe)
  executables = []
  if 'PATHEXT' in os.environ:
    exts = os.environ['PATHEXT'].split(os.pathsep)
    possible_exe_names = tuple(f'{exe}{ext}' for ext in exts) + (exe,)
  else:
    # Also try with .exe anyway, for WSL setups
    possible_exe_names = (exe,exe+'.exe')

  # When an insert path is specified, look there first
  if envvar:
    path_dirs = os.environ.get(envvar, '').split(os.pathsep)
  else:
    path_dirs = []
  if insert:
    candidates = [insert] + path_dirs
  else:
    candidates = path_dirs

  for path in candidates:
    for possible_exe_name in possible_exe_names:
      joined = os.path.join(path, possible_exe_name)
      if os.path.isfile(joined) and os.access(joined, flag):
        resolved_path = os.path.realpath(joined)
        logging.debug(f'Found {exe} as {resolved_path}')
        executables.append(resolved_path)
  
  return executables


# Find an executable in the PATH. This is aware of the (Windows) PATHEXT
# environment variable, and will automatically search an equivalent .exe (on all
# OSes, so this can be run from WSL).
def find_executable(exe: str) -> str | None:
  executables = enumerate_executables(exe=exe)
  if executables:
    return executables[0]
  return None


def docker_csharpier_version(docker: str, image: str) -> str | None:
  try:
    out = cmd_output(docker, 'run', '--rm', image, '--version')
    return get_semver(out.strip())
  except CalledProcessError:
    return None

# Run CSharpier as a Docker container, at the specified version. The current
# path will be mounted rw at /src inside the container and the current user and
# group ids will be mapped into the container.
def run_docker(version: str | None, image: str, argv: Sequence[str] | None = None) -> bool:
  # Adapt image specification to contain version
  request_version = False
  if version:
    if re.match(':[a-z0-9]+(?:[._-][a-z0-9]+)*$', image):
      logging.warning(f'Provided image {image} already contains a tag. Will not override with {version}')
      request_version = True
    else:
      image = image + ':' + version
  else:
    request_version = True

  # Find dotnet executable, cannot run without it
  docker = find_executable('docker')
  if not docker:
    logging.warning('docker cannot be found in PATH!')
    return None
  
  if request_version:
    version = docker_csharpier_version(docker, image)

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
    logging.info(f'Ran Docker container based on {image} with {" ".join(argv)}')
  else:
    logging.error(f'Cannot create Docker container from "{image}". Consider the --install option.')
  return result


# Turn on the x bits of the file passed as an argument. This will only sets the
# bits that are r to (also) x.
def make_executable(path):
  mode = os.stat(path).st_mode
  mode |= (mode & 0o444) >> 2    # copy R bits to X
  os.chmod(path, mode)


def dotnet_default_root() -> str | None:
  # dotnet tools install globally under USERPROFILE on windows and HOME
  # elsewhere
  home = os.environ.get('USERPROFILE', os.environ.get('HOME'))
  if not home:
    return None

  # Hidden dotnet directory
  root = os.path.join(home, '.dotnet')
  return root


def install_tooldir(version: str) -> str | None:
  root = dotnet_default_root()
  if root:
    if version:
      return os.path.join(root, 'pre-commit', 'csharpier', version)
    else:
      return os.path.join(root, 'tools')

  return None


# Install csharpier so that it will be accessible to all projects on the system.
# When no version: global installation. Otherwise, use specific directory for
# that version.
def install_csharpier(version: str | None = None) -> str | None:
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
      executables = enumerate_executables(exe=binary, envvar=None, flag=os.R_OK, insert=target)
      if executables:
        csharpier = executables[0]
        make_executable(csharpier)
        logging.info(f'Installed csharpier as {csharpier}')
        return csharpier
  else:
    logging.error('Failed to install csharpier!')

  return None


# Compare two version strings and return True if version1 >= version2
def is_version_greater_or_equal(version1: str, version2: str) -> bool:
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
  match = re.search(r'(\d+(?:\.\d+){0,2})', version)
  if match:
    return match.group(1)
  return None


# Actively run the csharpier command passed as an argument with the --version
# option and return the version string. Strips away the revision number from the
# version.
def csharpier_version(bin: Sequence[str]) -> str | None:
  setup_dotnet_environment()
  try:
    command = bin + ['--version']
    return get_semver(cmd_output(*command).strip())
  except CalledProcessError:
    return None


# Run csharpier directly. bin is how to run csharpier itself, argv are the
# arguments to csharpier. Both will be combined to form the command to run
def run_csharpier(bin: Sequence[str], argv: Sequence[str] | None = None, version: str | None = None) -> bool:
  if not version:
    version = csharpier_version(bin)
  if is_version_greater_or_equal(version, '1.0.0'):
    bin = bin + ['format']
  csharpier = ' '.join(bin)
  result = run_dotnet_command(bin + argv)
  if result:
    logging.info(f'Ran {csharpier} directly with {" ".join(argv)}')
  else:
    logging.error(f'"{csharpier}" cannot be run. Install csharpier manually or consider the --install option.')
  return result


def run_csharpier_as_binary(version: str | None, path: str | None = 'PATH', argv: Sequence[str] | None = None) -> bool:
  default_dir = install_tooldir(version)

  # List of possible binary names: name changed from dotnet-csharpier to
  # simply csharpier in version 1.0.0, so we will try both.
  binaries = ['dotnet-csharpier', 'csharpier']
  for binary in binaries:
    for exe in enumerate_executables(exe=binary, envvar=path, insert=default_dir):
      csharpier = [ exe ]
      if version:
        installed_version = csharpier_version(csharpier)
        if installed_version == version:
          return run_csharpier(csharpier, argv, version)
      else:
        return run_csharpier(csharpier, argv, version)

      installed_version = csharpier_version(csharpier)
      if version:
        if installed_version == version:
          return run_csharpier(csharpier, argv, version)
      else:
        return run_csharpier(csharpier, argv, version)
  return False


def run_csharpier_as_local_tool(version: str | None, argv: Sequence[str] | None = None) -> bool:
  dotnet = find_executable('dotnet')
  if not dotnet:
    return False
  csharpier = [ dotnet, 'csharpier' ]
  if version:
    installed_version = csharpier_version(csharpier)
    if installed_version == version:
      return run_csharpier(csharpier, argv, version)
  else:
    return run_csharpier(csharpier, argv, version)
  return False


def run_csharpier_as_tool(version: str | None, argv: Sequence[str] | None = None) -> bool:
  if run_csharpier_as_local_tool(version, argv=argv):
    return True
  return run_csharpier_as_binary(version, path=None, argv=argv)


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
    default='bin tool docker',
    help='Methods to find csharpier, and in which order. Space separated tokens: bin, tool or docker'
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
    version = version.lstrip('v')
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
    if m == 'bin':
      if run_csharpier_as_binary(version, argv=args.args):
        return 0
    if m == 'tool':
      if run_csharpier_as_tool(version, argv=args.args):
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