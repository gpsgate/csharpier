# CSharpier in Docker

This project implements:
+ A non-root Docker [image] that runs any published version of [CSharpier].
+ An automated [workflow] to build and publish multi-platform [images] when new
  versions of CSharpier are [released](#version-capture). Images are tagged with
  the version of [CSharpier]. The image tagged `latest` always points to the
  latest release of [CSharpier] at the time of the run.
+ A [pre-commit] [hook] to run [CSharpier] on the files passed to `pre-commit`.
  The hook is a forgiving wrapper [implemented] in python: It will attempt to
  run `csharpier` using `dotnet` first. If that fails, it will attempt to run it
  using the `latest` Docker [image][images] built by this project.

  [image]: ./Dockerfile
  [CSharpier]: https://github.com/belav/csharpier
  [workflow]: ./.github/workflows/csharpier.yml
  [images]: https://github.com/gpsgate/csharpier/pkgs/container/csharpier
  [pre-commit]: https://pre-commit.com/
  [hook]: ./.pre-commit-hooks.yaml
  [implemented]: ./pre_commit_hooks/csharpier.py

## Usage

### From Docker

To use the Docker image, run the following command from the root of your tree.
The command maps your current directory to the container's working directory and
performs user translation, so that CSharpier can access your files. The example
below just prints the help, replace the `--help` flag with any arguments and
[options] accepted by CSharpier.

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
CSharpier will store file-related information in its cache at the root of your
tree in a directory that you will have to ignore from version control.

```yaml
  - repo: https://github.com/gpsgate/csharpier
    rev: v0.2.0
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

The [workflow] is set to run twice a week, and will only build and push new
images if either this project has changed or a new version of CSharpier has been
released. Decisions are made based on the [history] of the repository and the
build date of the target image: if the build date of the target image is newer
than the last commit to the repository, the image is not rebuilt. This is a
good-enough approximation for the scenario where the [workflow] is triggered at
few regular intervals and the [CSharpier] project is not updated too often.

  [build]: ./hooks/build+push
  [history]: https://github.com/gpsgate/csharpier/commits/main

## Development

When developing this project, you can run and test its main [build] logic
without using the GitHub Actions workflow. To do so, you can run the following
command from the root of your tree. The command will perform all the steps
described [above](#version-capture), only making the built images available to
your local installation.

```bash
BUILDX_OPERATION=--load ./hooks/build+push
```
