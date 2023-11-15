FROM mcr.microsoft.com/dotnet/sdk:7.0 as build
ARG CSHARPIER_VERSION=0.26.1

RUN dotnet tool install --tool-path /tmp/tools csharpier --version ${CSHARPIER_VERSION}

FROM mcr.microsoft.com/dotnet/runtime:7.0

RUN groupadd --gid 1000 dotnet \
    && useradd --uid 1000 --gid dotnet --shell /bin/bash --create-home dotnet

COPY --from=build /tmp/tools /home/dotnet/.dotnet/tools
RUN chown -R dotnet:dotnet /home/dotnet/.dotnet
USER dotnet

ENTRYPOINT ["/home/dotnet/.dotnet/tools/dotnet-csharpier"]
