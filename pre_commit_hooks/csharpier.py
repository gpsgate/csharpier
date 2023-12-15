from __future__ import annotations

import argparse
import os
import subprocess
import json
import sys
from typing import Any, Sequence

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
  if os.environ.get('PRE_COMMIT_HOOK_CSHARPIER_DEBUG'):
    print(f'Running command: {cmd} with kwargs: {kwargs}', file=sys.stderr)
    if os.environ.get('PRE_COMMIT_HOOK_CSHARPIER_DEBUG') == '2':
      for k, v in os.environ.items():
        print(f'\tENV: {k}={v}', file=sys.stderr)
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

def run_docker(argv: Sequence[str] | None = None) -> bool:
  try:
    image = os.environ.get('PRE_COMMIT_HOOK_CSHARPIER_DOCKER', 'ghcr.io/gpsgate/csharpier')
    out = cmd_output('docker', 'run',
                        '--rm',
                        *get_docker_user(),
                        '-v', f'{_get_docker_path(os.getcwd())}:/src:rw,Z',
                        '-w', '/src',
                        '-t',
                        image, *argv)
    if out:
      print(out)
    return True
  except CalledProcessError as e:
    if e.stderr:
      print(e.stderr, file=sys.stderr)
    if e.stdout:
      print(e.stdout)
  except FileNotFoundError:
    print('docker is not installed. Ran out of options. Giving up!', file=sys.stderr)
  return False

def run_csharpier(argv: Sequence[str] | None = None) -> bool:
  try:
    out = cmd_output('dotnet', 'csharpier', *argv)
    if out:
      print(out)
    return True
  except CalledProcessError as e:
    if e.stderr:
      print(e.stderr, file=sys.stderr)
    if e.stdout:
      print(e.stdout)
  except FileNotFoundError:
    print('dotnet tool "csharpier" is not installed. Will run through Docker. You can also install it using "dotnet tool install -g dotnet-csharpier".', file=sys.stderr)
  return False

def main() -> int:
  args = sys.argv[1:]
  if not run_csharpier(args):
    if not run_docker(args):
      return 1
  return 0

if __name__ == '__main__':
  raise SystemExit(main())