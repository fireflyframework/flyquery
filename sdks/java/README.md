<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark) and (max-width: 600px)" srcset="../../docs/assets/brand/banner-dark-mobile.svg">
  <source media="(max-width: 600px)" srcset="../../docs/assets/brand/banner-light-mobile.svg">
  <source media="(prefers-color-scheme: dark)" srcset="../../docs/assets/brand/banner-dark.svg">
  <img src="../../docs/assets/brand/banner-light.svg" alt="flyquery by Firefly" width="100%">
</picture>

### **Java SDK** &nbsp;&middot;&nbsp; Spring Boot 3.5.9 &nbsp;&middot;&nbsp; Java 25 &nbsp;&middot;&nbsp; WebFlux

</div>

The Java client uses WebClient and Reactor `Mono` responses. Generated API classes
and request/response models come from the service's OpenAPI snapshot. A
`com.firefly.flyquery.FlyqueryClient` wrapper groups API resources and configures
default headers.

## Install

The current published release is 26.10.3. Candidate source prepares 26.10.4;
its native acceptance and publication are pending. For the published release,
use the matching Maven coordinate:

```xml
<dependency>
  <groupId>com.firefly</groupId>
  <artifactId>flyquery-sdk</artifactId>
  <version>26.10.3</version>
</dependency>
```

The publisher targets GitHub Packages at
`https://maven.pkg.github.com/fireflyframework/flyquery`. GitHub Packages requires
Maven authentication. See the [release](https://github.com/fireflyframework/flyquery/releases/tag/v26.10.3)
for downloadable artifacts and use the service's matching version. Earlier
release artifacts keep their original registry coordinates.

The POM targets Java 25 and Spring Boot 3.5.9. If your application does not inherit
the Spring Boot parent, import the matching `spring-boot-dependencies` BOM.

## Call a generated resource

Generated methods require explicit tenant and workspace parameters. Default
headers do not remove those arguments. Use the UUID returned by workspace
creation when working with datasets.

```java
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.api.WorkspacesApi;

ApiClient api = new ApiClient();
api.setBasePath(System.getenv("FLYQUERY_URL"));
String tenant = System.getenv("FLYQUERY_TENANT_ID");
String workspace = System.getenv("FLYQUERY_WORKSPACE_ID");

new WorkspacesApi(api)
    .listWorkspaces(tenant, workspace, null, null, null, 20, 0, null)
    .subscribe(page -> System.out.println(page.getItems()));
```

A convenience client's `workspaces()`, `datasets()` and other accessors expose
these same generated API objects. Keep a client scoped to one tenant/workspace.
For workspace or dataset creation, fall back only after a 404; a catch-all error
handler can turn an authorization or server failure into an unwanted write.
Concurrent creation can still return a 409.

## Authentication, errors and streams

Scope headers select the tenant and workspace. Configure deployment authentication
and bearer credentials where required. Agent routes use an issued agent token;
call the generated `Agent*Api` classes rather than adding a token to a user-route
request and expecting its route to change. Read the
[security model](../../docs/security-model.md) before issuing tokens.

Generated methods report unsuccessful HTTP responses through
`WebClientResponseException`. Inspect its status and response body. Bulk uploads
and question batches also carry per-item outcomes; inspect those after a
successful HTTP response. Uploads and natural-language questions can call your
configured model providers.

Streaming methods expose their response through the generated WebClient methods.
Choose the raw `ResponseSpec` when you need SSE frames; do not assume a unary
`Mono` response is a decoded event stream. The
[pipeline guide](../../docs/pipeline.md) documents event types. Configure connection
and request timeouts in your application's WebClient; a client timeout does not
establish server cancellation or an operating system sandbox.

## API and development

Current resources include workspaces, datasets, files, tables, schema objects and
changes, semantic definitions, relations, queries, history, audit, statistics,
billing and scoped agent endpoints. Refer to the checked-in
[OpenAPI snapshot](../../openapi.json) and generated source signatures for the
complete contract.

```bash
# From the repository root:
task openapi-snapshot
task sdk:java
# Then:
cd sdks/java
mvn verify
```

Handwritten files are preserved by `.openapi-generator-ignore`. Read the
[SDK overview](../../docs/sdks.md) for scope, versioning and the Python client.
Licensed under Apache 2.0. Copyright Firefly Software Foundation.
