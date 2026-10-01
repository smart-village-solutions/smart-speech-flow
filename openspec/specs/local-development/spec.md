# local-development Specification

## Purpose
Define what a developer needs to build and run the stack locally: the default Compose file builds every image from this repository alone, so a fresh clone with the documented `.env` setup is enough.

## Requirements

### Requirement: Default Compose build is self-contained

The default `docker-compose.yml` SHALL build every image from this repository
alone, so that a fresh clone with `.env` copied from `.env.example` can run
`docker compose build`.

#### Scenario: Fresh clone

- **WHEN** a developer clones only this repository, copies `.env.example` to `.env` and runs `docker compose build`
- **THEN** every build context resolves inside the repository and the build does not require a sibling checkout

#### Scenario: Out-of-repository context is added

- **WHEN** a service in `docker-compose.yml` declares a build context outside the repository
- **THEN** the hermetic test suite fails and names that service
