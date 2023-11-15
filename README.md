# CSharpier in Docker

This project implements:
+ A Docker [image] that runs any published version of [CSharpier].
+ An automated [workflow] to build and publish [images] when new versions of
  CSharpier are released.
+ A [pre-commit] [hook] to run CSharpier on all staged files.

  [image]: ./Dockerfile
  [CSharpier]: https://github.com/belav/csharpier
  [workflow]: ./.github/workflows/csharpier.yml
  [images]: https://github.com/gpsgate/csharpier/pkgs/container/csharpier
  [pre-commit]: https://pre-commit.com/
  [hook]: ./.pre-commit-hooks.yaml

## Usage

### From Docker

To use the Docker image, run the following command from the root of your tree.
The example below just prints the help, replace the `--help` flag with any
arguments and [options] accepted by CSharpier.

```bash
docker run \
  --rm -it \
  -v "$(pwd):$(pwd)" \
  -u $(id -u):$(id -g) \
  -w "$(pwd)" \
  ghcr.io/gpsgate/csharpier:latest \
    --help
```

  [options]: https://csharpier.com/docs/CLI#command-line-options

### From pre-commit

Add the following to your `.pre-commit-config.yaml` file. You might want to
check the latest version of the repository [here][history] and change the `rev`
key. You might also want to remove the `--no-cache` argument, in which case
CSharpier will store file-releted information in its cache at the root of your
tree in a directory that you will have to ignore from version control.

```yaml
  - repo: https://github.com/gpsgate/csharpier
    rev: a216c9609b77b324988ab3b74e5bf8d0aae50321
    hooks:
      - id: csharpier
        args:
          - --no-cache
```

  [history]: https://github.com/gpsgate/csharpier/commits/main
