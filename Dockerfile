ARG DOTNET_VERSION=7.0
FROM mcr.microsoft.com/dotnet/sdk:${DOTNET_VERSION} AS build
ARG CSHARPIER_VERSION=0.26.1

RUN dotnet tool install --tool-path /tmp/tools csharpier --version ${CSHARPIER_VERSION}

FROM mcr.microsoft.com/dotnet/runtime:${DOTNET_VERSION}

ARG LABEL_AUTHOR="Emmanuel Frécon <efrecon+github@gmail.com>"
ARG LABEL_URL=https://github.com/gpsgate/csharpier
ARG LABEL_DESCRIPTION="CSharpier is an opinionated code formatter for c#"
ARG LABEL_TITLE=gpsgate/csharpier

# Metadata
LABEL MAINTAINER="${LABEL_AUTHOR}"
LABEL org.opencontainers.image.title="${LABEL_TITLE}"
LABEL org.opencontainers.image.description="${LABEL_DESCRIPTION}"
LABEL org.opencontainers.image.authors="${LABEL_AUTHOR}"
LABEL org.opencontainers.image.url="${LABEL_URL}"

RUN groupadd --gid 1000 dotnet \
    && useradd --uid 1000 --gid dotnet --shell /bin/bash --create-home dotnet

COPY --from=build /tmp/tools /home/dotnet/.dotnet/tools
RUN chown -R dotnet:dotnet /home/dotnet/.dotnet
USER dotnet

# Turn off telemetry and dotnet preamble to prevent polluting stdout from
# CI/pre-commit.
ENV \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=true

ENTRYPOINT ["/home/dotnet/.dotnet/tools/dotnet-csharpier"]
