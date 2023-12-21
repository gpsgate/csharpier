# CSharpier in Docker

This project implements:
+ A non-root Docker [image] that runs any published version of [CSharpier].
+ An automated [workflow] to build and publish multi-platform [images] when new
  versions of CSharpier are [released](#version-capture). Images are tagged with
  the version of [CSharpier]. The image tagged `latest` always points to the
  latest release of [CSharpier] at the time of the run.
+ A [pre-commit] [hook] to run [CSharpier] on the files passed to `pre-commit`.
  The hook is a wrapper [implemented] in python. The wrapper is designed to be
  forgiving and as little intrusive as possible. By default, it will attempt to
  run `csharpier` using `dotnet` first. If that fails, it will attempt to run it
  using the `latest` Docker [image][images] built by this project. But it can be
  told to install `csharpier` (globally), even at a specific version and to run
  it. See all recognised [options](#cli-options) that can be set through the
  YAML [`args`][args] hook configuration key.

  [image]: ./Dockerfile
  [CSharpier]: https://github.com/belav/csharpier
  [workflow]: ./.github/workflows/csharpier.yml
  [images]: https://github.com/gpsgate/csharpier/pkgs/container/csharpier
  [pre-commit]: https://pre-commit.com/
  [hook]: ./.pre-commit-hooks.yaml
  [implemented]: ./pre_commit_hooks/csharpier.py
  [args]: https://pre-commit.com/#config-args

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

**Note**: The `rev` is **NOT** the version of csharpier to run, but rather the
version of the hook, i.e. a release of this project. Read further for how to
pinpoint a specific version of CSharpier.

```yaml
  - repo: https://github.com/gpsgate/csharpier
    rev: v0.4.0
    hooks:
      - id: csharpier
        args:
          - --no-cache
```

If you want to enforce a version of CSharpier, you can do that through the
`--version` option. When doing so, and as per the default, this hook will
download and install CSharpier at that exact version in a non-standard directory
in order to be able run it. Below is an example hook specification. A `--`
separator is used to mark the end of the options to the hook and the beginning
of the options that are blindly passed to CSharpier.

```yaml
  - repo: https://github.com/gpsgate/csharpier
    rev: v0.4.0
    hooks:
      - id: csharpier
        args:
          - --version=0.26.7
          - --
          - --no-cache
```

The pre-commit hook can be controlled using a number of environment
[variables](#environment-variables), all starting with
`PRE_COMMIT_HOOK_CSHARPIER_` and a number of [options](#cli-options). Use
options to change the behaviour for all users of your repository, e.g.
pinpointing the version to ensure all code is formatted the same way. Use
environment variables to adapt to your local client-side requirements, e.g.
preventing any local installation and running as a Docker container.

  [history]: https://github.com/gpsgate/csharpier/commits/main

#### CLI Options

The CLI options can be used from the YAML pre-commit configuration, using the
`args` key. The recognised options are:

+ `-s` or `--search` is a space separated list of tokens describing how to look
  for/run CSharpier and in which order. The recognised tokens are:
  + `bin`: run `dotnet-csharpier` from the `PATH` or the one that the hook
    installs (see: `--install`).
  + `tool`: run `csharpier` as a `dotnet` tool, or the one that the hook
    installs (see: `--install`).
  + `docker`: run CSharpier using the Docker images created by this project. If
    a tag (version) is provided, it will be used as is, even though the
    `--version` is specified.
+ `-d` or `--docker` is the fully qualified Docker image to run whenever
  necessary.
+ `-i` or `--install` specifies when to install CSharpier. Possible values are:
  + `never`: Never install CSharpier. The hook will run with the matching one
    that it can find, if possible.
  + `version`: Only install CSharpier when a specific version is requested.
  Installation occurs in the user´s main directory, but at a non-standard
  location to avoid clashing with other existing installations.
  + `always`: Always install CSharpier. When no version is specified, the
  default, `csharpier` will be installed globally, i.e. within the user's main
  directory. Otherwise, see `version` above.
+ `-v` or `--version` is the version of CSharpier to install, if necessary, and
  run. This version will also be used when running as a Docker container, unless
  the image provided through the `--docker` option already contained a tag. When
  no version is specified, the default, the existing and installed CSharpier
  will be used, if found, otherwise the `latest` Docker image.
+ `-l` or `--log-level` is the log level. One of `DEBUG`, `INFO`, `WARNING`,
  `ERROR` or `CRITICAL`.

When CSharpier is installed at a specific version, the installation path will be
the directory called `.dotnet/pre-commit/csharpier/{version}` under your home
directory. The hook never cleans up that directory, so it can reuse installed
CSharpier across runs.

#### Environment Variables

Environment variables match the long options as follows. When an environment
variable is set, its value will prevail over the value of the command-line
option. This is because the hook is meant to be used from a YAML specification
that is checked in your repository. Environment variables provide a way to
depart from centralised options to adapt to local installation "quirks".

+ `PRE_COMMIT_HOOK_CSHARPIER_SEARCH` is the same as `--search`.
+ `PRE_COMMIT_HOOK_CSHARPIER_DOCKER` is the same as `--docker`.
+ `PRE_COMMIT_HOOK_CSHARPIER_INSTALL` is the same as `--install`.
+ `PRE_COMMIT_HOOK_CSHARPIER_VERSION` is the same as `--version`. Setting this
  variable is highly discouraged as you would use a version different than the
  one recommended by your repository maintainers.
+ `PRE_COMMIT_HOOK_CSHARPIER_LOG_LEVEL` is the same as `--log-level`.

## Version Capture (Docker)

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

### Docker Image

When developing this project, you can run and test its main [build] logic
without using the GitHub Actions workflow. To do so, you can run the following
command from the root of your tree. The command will perform all the steps
described [above](#version-capture), only making the built images available to
your local installation.

```bash
BUILDX_OPERATION=--load ./hooks/build+push
```

### Python `pre-commit` Hook

When developing the `pre-commit` hook, you can test it using the
[`try-repo`][try-repo] sub-command. You can temporarily specify arguments using
the [`args`][hook-args] key in the [YAML](./.pre-commit-hooks.yaml)
configuration of this hook. In order to be able to see the loggers output, you
will need to run with the `--verbose` flag to the `try-repo` sub-command.

  [try-repo]: https://pre-commit.com/#pre-commit-try-repo
  [hook-args]: https://pre-commit.com/#hooks-args
