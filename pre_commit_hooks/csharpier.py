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

# Find an executable in the PATH. This is aware of the (Windows) PATHEXT
# environment variable, and will automatically search an equivalent .exe (on all
# OSes, so this can be run from WSL).
def find_executable(exe: str) -> str | None:
  exe = os.path.normpath(exe)
  if os.sep in exe:
    return exe

  if 'PATHEXT' in os.environ:
    exts = os.environ['PATHEXT'].split(os.pathsep)
    possible_exe_names = tuple(f'{exe}{ext}' for ext in exts) + (exe,)
  else:
    # Also try with .exe anyway, for WSL setups
    possible_exe_names = (exe,exe+'.exe')

  for path in os.environ.get('PATH', '').split(os.pathsep):
    for possible_exe_name in possible_exe_names:
      joined = os.path.join(path, possible_exe_name)
      if os.path.isfile(joined) and os.access(joined, os.X_OK):
        logging.debug(f'Found {exe} as {joined}')
        return joined
  
  return None

# Run CSharpier as a Docker container, at the specified version. The current
# path will be mounted rw at /src inside the container and the current user and
# group ids will be mapped into the container.
def run_docker(version: str | None, image: str, argv: Sequence[str] | None = None) -> bool:
  # Adapt image specification to contain version
  if version:
    if re.match(':[a-z0-9]+(?:[._-][a-z0-9]+)*$', image):
      logging.warning(f'Provided image {image} already contains a tag. Will not override with {version}')
    else:
      image = image + ':' + version

  # Find dotnet executable, cannot run without it
  docker = find_executable('docker')
  if not docker:
    logging.warning('docker cannot be found in PATH!')
    return None

  run = [ 'docker', 'run',
            '--rm',
            *get_docker_user(),
            '-v', f'{_get_docker_path(os.getcwd())}:/src:rw,Z',
            '-w', '/src',
            '-t',
            image ] + (argv if argv is not None else [])
  result = run_command(argv=run)
  if result:
    logging.info(f'Ran {image} on {" ".join(argv)}')
  else:
    logging.error(f'Cannot create Docker container from "{image}". Consider the --install option.')
  return result

# Turn on the x bits of the file passed as an argument. This will only sets the
# bits that are r to (also) x.
def make_executable(path):
  mode = os.stat(path).st_mode
  mode |= (mode & 0o444) >> 2    # copy R bits to X
  os.chmod(path, mode)

# Find csharpier. When no version is specified, look for it when dotnet installs
# global tools. When a version is specified, look for it where the hook chooses
# to install in that case.
def find_csharpier(version: str | None) -> str | None:
  # dotnet tools install globally under USERPROFILE on windows and HOME
  # elsewhere
  home = os.environ.get('USERPROFILE', os.environ.get('HOME'))
  if not home:
    return None

  # Hidden dotnet directory
  root = os.path.join(home, '.dotnet')

  # global or "home-made" location
  if not version:
    bin = os.path.join(root, 'tools', 'dotnet-csharpier')
  else:
    bin = os.path.join(root, 'pre-commit', 'csharpier', version, 'dotnet-csharpier')

  if os.path.exists(bin):
    logging.debug(f'csharpier found as {bin}')
    return bin
  # Also try with .exe for WSL setups
  bin = bin+'.exe'
  if os.path.exists(bin):
    logging.debug(f'csharpier found as {bin}')
    return bin

  return None


# Install csharpier so that it will be accessible to all projects on the system.
# When no version: global installation. Otherwise, use specific directory for
# that version.
def install_csharpier(version: str | None) -> str | None:
  # dotnet tools install globally under USERPROFILE on windows and HOME
  # elsewhere
  home = os.environ.get('USERPROFILE', os.environ.get('HOME'))
  if not home:
    logging.critical('Could not find a home directory!')
    return None

  # Find dotnet executable, cannot run without it
  dotnet = find_executable('dotnet')
  if not dotnet:
    logging.critical('dotnet cannot be found in PATH!')
    return None

  # Hidden dotnet directory, create if necessary
  root = os.path.join(home, '.dotnet')
  if not os.path.exists(root):
    os.makedirs(root)

  if version:
    # Version is specified, install the specific version of csharpier under the
    # same root directory as other dotnet stuff, but using a different hierarchy
    # since we will need to be able to point to that specific version/location
    # when running.
    target = os.path.join(root, 'pre-commit', 'csharpier', version)
    if not os.path.exists(target):
      os.makedirs(target)
    install = [ dotnet, 'tool', 'install', 'csharpier',
                  '--tool-path', target,
                  '--version', version ]
  else:
    # No version specified, install the latest version of csharpier, globally
    install = [ dotnet, 'tool', 'install', '-g', 'dotnet-csharpier' ]

  if run_command(install):
    csharpier = find_csharpier(version)
    make_executable(csharpier)
    logging.info(f'Installed csharpier as {csharpier}')
    return csharpier
  else:
    logging.error('Failed to install csharpier!')

  return None


# Run csharpier directly. bin is how to run csharpier itself, argv are the
# arguments to csharpier. Both will be combined to form the command to run
def run_csharpier(bin: Sequence[str], argv: Sequence[str] | None = None) -> bool:
  csharpier = ' '.join(bin)
  result = run_command(bin + argv)
  if result:
    logging.info(f'Ran {csharpier} on {" ".join(argv)}')
  else:
    logging.error(f'"{csharpier}" cannot be run. Install csharpier manually or consider the --install option.')
  return result

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
  if version:
    logging.debug(f'(Install and) run csharpier version {version}')
    for m in methods:
      # Look for csharpier at the requested version in the directory of our
      # liking, perhaps install it and run it from there.
      if m == 'bin' or m == 'tool':
        csharpier = find_csharpier(version)
        if not csharpier:
          if install == 'always' or install == 'version':
            csharpier = install_csharpier(version)
        if csharpier:
          if run_csharpier([csharpier], args.args):
            return 0
      # Run csharpier as a docker container, at the specified version.
      if m == 'docker' and run_docker(image=image, version=version, argv=args.args):
        return 0
  else:
    logging.debug('(Install and) run latest/existing csharpier')
    for m in methods:
      if install == 'always':
        # When we should always install, install csharpier (globally) if it
        # cannot be found and run it.
        if m == 'bin' or m == 'tool':
          csharpier = find_csharpier()
          if not csharpier:
            csharpier = install_csharpier()
          if csharpier:
            if run_csharpier([csharpier], args.args):
              return 0
      else:
        # Try running it from the PATH as dotnet-csharpier
        if m == 'bin':
          csharpier = find_executable('dotnet-csharpier')
          if csharpier and run_csharpier([csharpier], args.args):
            return 0
        # Try running it through dotnet, i.e. let dotnet find it as a tool.
        if m == 'tool':
          dotnet = find_executable('dotnet')
          if dotnet and run_csharpier([dotnet, 'csharpier'], args.args):
            return 0
      # Run csharpier as a docker container, this will use the latest (by
      # default, but controlled through the --docker option).
      if m == 'docker' and run_docker(image=image, version=version, argv=args.args):
        return 0

  return 1

if __name__ == '__main__':
  raise SystemExit(main())