# CSharpier in Docker

This project implements:
+ A Docker [image] that runs any published version of [CSharpier].
+ An automated [workflow] to build and publish [images] when new versions of
  CSharpier are released.
+ A [pre-commit] [hook] to run the latest CSharpier on all staged files.

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

## Version Capture

The main Docker [image] is parameterised by a number of options/variables. These
options will be set at build time from the [workflow] and its main [build]
implementation script. The [build] script uses the GitHub API to fetch the list
of known versions of [CSharpier] at the time of the run and will automatically
build and push an image for each of them. In addition, the script generates a
`latest` tag for the latest version of CSharpier. Finally, it is able to adapt
to historical changes in the CSharpier dependencies (net7/net8 SDK).

The [workflow] is set to run once a week, and will only build and push new
images if either this project has changed or a new version of CSharpier has been
released.

  [build]: ./hooks/build+push

## Development

When developing this project, you can run and test its main [build] logic
without using the GitHub Actions workflow. To do so, you can run the following
command from the root of your tree. The command will perform all the steps
described [above](#version-capture), only making the built images available to
your local installation.

```bash
BUILDX_OPERATION=--load ./hooks/build+push
```
