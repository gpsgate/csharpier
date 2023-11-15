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
