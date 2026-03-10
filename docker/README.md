# csharpier Docker image

This builds a Docker image that runs the csharpier tool as an entrypoint.
The [entrypoint](./csharpier.sh) is able to pick the proper path to the binary,
which has changed across release history.
Use the [build+push](../hooks/build+push) script to build and push images tagged as the versions of the main [csharpier] project.

  [csharpier]: https://github.com/belav/csharpier
