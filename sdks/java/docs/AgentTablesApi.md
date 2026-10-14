# AgentTablesApi

All URIs are relative to *http://localhost*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**getSchemaObject**](AgentTablesApi.md#getSchemaObject) | **GET** /api/v1/agent/schema-objects/{object_id} |  |
| [**getTable**](AgentTablesApi.md#getTable) | **GET** /api/v1/agent/tables/{table_id} |  |
| [**getTableByName**](AgentTablesApi.md#getTableByName) | **GET** /api/v1/agent/tables/by-name/{name} |  |
| [**listChanges**](AgentTablesApi.md#listChanges) | **GET** /api/v1/agent/tables/{table_id}/changes |  |
| [**listObjects**](AgentTablesApi.md#listObjects) | **GET** /api/v1/agent/tables/{table_id}/objects |  |
| [**listSnapshots**](AgentTablesApi.md#listSnapshots) | **GET** /api/v1/agent/tables/{table_id}/snapshots |  |
| [**listTables**](AgentTablesApi.md#listTables) | **GET** /api/v1/agent/datasets/{dataset_id}/tables |  |
| [**searchTables**](AgentTablesApi.md#searchTables) | **GET** /api/v1/agent/tables |  |



## getSchemaObject

> SchemaObjectRead getSchemaObject(objectId, xAgentToken, xCorrelationId)



### Example

```java
// Import classes:
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.ApiException;
import com.firefly.flyquery.Configuration;
import com.firefly.flyquery.auth.*;
import com.firefly.flyquery.models.*;
import com.firefly.flyquery.api.AgentTablesApi;

public class Example {
    public static void main(String[] args) {
        ApiClient defaultClient = Configuration.getDefaultApiClient();
        defaultClient.setBasePath("http://localhost");
        
        // Configure API key authorization: AgentToken
        ApiKeyAuth AgentToken = (ApiKeyAuth) defaultClient.getAuthentication("AgentToken");
        AgentToken.setApiKey("YOUR API KEY");
        // Uncomment the following line to set a prefix for the API key, e.g. "Token" (defaults to null)
        //AgentToken.setApiKeyPrefix("Token");

        AgentTablesApi apiInstance = new AgentTablesApi(defaultClient);
        String objectId = "objectId_example"; // String | 
        String xAgentToken = "fqt_live_aBcDeF1234567890aBcDeF1234567890"; // String | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
        UUID xCorrelationId = UUID.fromString("550e8400-e29b-41d4-a716-446655440000"); // UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
        try {
            SchemaObjectRead result = apiInstance.getSchemaObject(objectId, xAgentToken, xCorrelationId);
            System.out.println(result);
        } catch (ApiException e) {
            System.err.println("Exception when calling AgentTablesApi#getSchemaObject");
            System.err.println("Status code: " + e.getCode());
            System.err.println("Reason: " + e.getResponseBody());
            System.err.println("Response headers: " + e.getResponseHeaders());
            e.printStackTrace();
        }
    }
}
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **objectId** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**SchemaObjectRead**](SchemaObjectRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |


## getTable

> TableRead getTable(tableId, xAgentToken, xCorrelationId)



### Example

```java
// Import classes:
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.ApiException;
import com.firefly.flyquery.Configuration;
import com.firefly.flyquery.auth.*;
import com.firefly.flyquery.models.*;
import com.firefly.flyquery.api.AgentTablesApi;

public class Example {
    public static void main(String[] args) {
        ApiClient defaultClient = Configuration.getDefaultApiClient();
        defaultClient.setBasePath("http://localhost");
        
        // Configure API key authorization: AgentToken
        ApiKeyAuth AgentToken = (ApiKeyAuth) defaultClient.getAuthentication("AgentToken");
        AgentToken.setApiKey("YOUR API KEY");
        // Uncomment the following line to set a prefix for the API key, e.g. "Token" (defaults to null)
        //AgentToken.setApiKeyPrefix("Token");

        AgentTablesApi apiInstance = new AgentTablesApi(defaultClient);
        String tableId = "tableId_example"; // String | 
        String xAgentToken = "fqt_live_aBcDeF1234567890aBcDeF1234567890"; // String | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
        UUID xCorrelationId = UUID.fromString("550e8400-e29b-41d4-a716-446655440000"); // UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
        try {
            TableRead result = apiInstance.getTable(tableId, xAgentToken, xCorrelationId);
            System.out.println(result);
        } catch (ApiException e) {
            System.err.println("Exception when calling AgentTablesApi#getTable");
            System.err.println("Status code: " + e.getCode());
            System.err.println("Reason: " + e.getResponseBody());
            System.err.println("Response headers: " + e.getResponseHeaders());
            e.printStackTrace();
        }
    }
}
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **tableId** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**TableRead**](TableRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |


## getTableByName

> TableRead getTableByName(name, xAgentToken, datasetId, xCorrelationId)



### Example

```java
// Import classes:
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.ApiException;
import com.firefly.flyquery.Configuration;
import com.firefly.flyquery.auth.*;
import com.firefly.flyquery.models.*;
import com.firefly.flyquery.api.AgentTablesApi;

public class Example {
    public static void main(String[] args) {
        ApiClient defaultClient = Configuration.getDefaultApiClient();
        defaultClient.setBasePath("http://localhost");
        
        // Configure API key authorization: AgentToken
        ApiKeyAuth AgentToken = (ApiKeyAuth) defaultClient.getAuthentication("AgentToken");
        AgentToken.setApiKey("YOUR API KEY");
        // Uncomment the following line to set a prefix for the API key, e.g. "Token" (defaults to null)
        //AgentToken.setApiKeyPrefix("Token");

        AgentTablesApi apiInstance = new AgentTablesApi(defaultClient);
        String name = "name_example"; // String | 
        String xAgentToken = "fqt_live_aBcDeF1234567890aBcDeF1234567890"; // String | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
        String datasetId = "datasetId_example"; // String | 
        UUID xCorrelationId = UUID.fromString("550e8400-e29b-41d4-a716-446655440000"); // UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
        try {
            TableRead result = apiInstance.getTableByName(name, xAgentToken, datasetId, xCorrelationId);
            System.out.println(result);
        } catch (ApiException e) {
            System.err.println("Exception when calling AgentTablesApi#getTableByName");
            System.err.println("Status code: " + e.getCode());
            System.err.println("Reason: " + e.getResponseBody());
            System.err.println("Response headers: " + e.getResponseHeaders());
            e.printStackTrace();
        }
    }
}
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **name** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **datasetId** | **String**|  | [optional] |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**TableRead**](TableRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |


## listChanges

> Mono<PaginatedSchemaChangeRead> listChanges(tableId, xAgentToken, xCorrelationId)



### Example

```java
import java.time.Duration;
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.api.AgentTablesApi;
import com.firefly.flyquery.model.PaginatedSchemaChangeRead;
import org.springframework.web.reactive.function.client.WebClientResponseException;

public class Example {
    public static void main(String[] args) {
        ApiClient client = new ApiClient();
        client.setBasePath(System.getenv("FLYQUERY_URL"));
        client.addDefaultHeader("X-Tenant-Id", System.getenv("FLYQUERY_TENANT_ID"));
        client.addDefaultHeader("X-Workspace-Id", System.getenv("FLYQUERY_WORKSPACE_ID"));
        AgentTablesApi api = new AgentTablesApi(client);
        String token = System.getenv("FLYQUERY_AGENT_TOKEN");
        String tableId = System.getenv("FLYQUERY_TABLE_ID");
        try {
            PaginatedSchemaChangeRead page = api.listChanges(tableId, token, null).block(Duration.ofSeconds(15));
            if (page == null) throw new IllegalStateException("The API returned no page");
            System.out.println(page.getItems());
        } catch (WebClientResponseException e) {
            System.err.println("HTTP " + e.getStatusCode());
            throw e;
        }
    }
}
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **tableId** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**PaginatedSchemaChangeRead**](PaginatedSchemaChangeRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |


## listObjects

> Mono<PaginatedSchemaObjectRead> listObjects(tableId, xAgentToken, xCorrelationId)



### Example

```java
import java.time.Duration;
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.api.AgentTablesApi;
import com.firefly.flyquery.model.PaginatedSchemaObjectRead;
import org.springframework.web.reactive.function.client.WebClientResponseException;

public class Example {
    public static void main(String[] args) {
        ApiClient client = new ApiClient();
        client.setBasePath(System.getenv("FLYQUERY_URL"));
        client.addDefaultHeader("X-Tenant-Id", System.getenv("FLYQUERY_TENANT_ID"));
        client.addDefaultHeader("X-Workspace-Id", System.getenv("FLYQUERY_WORKSPACE_ID"));
        AgentTablesApi api = new AgentTablesApi(client);
        String token = System.getenv("FLYQUERY_AGENT_TOKEN");
        String tableId = System.getenv("FLYQUERY_TABLE_ID");
        try {
            PaginatedSchemaObjectRead page = api.listObjects(tableId, token, null).block(Duration.ofSeconds(15));
            if (page == null) throw new IllegalStateException("The API returned no page");
            System.out.println(page.getItems());
        } catch (WebClientResponseException e) {
            System.err.println("HTTP " + e.getStatusCode());
            throw e;
        }
    }
}
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **tableId** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**PaginatedSchemaObjectRead**](PaginatedSchemaObjectRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |


## listSnapshots

> Mono<PaginatedSnapshotRead> listSnapshots(tableId, xAgentToken, xCorrelationId)



### Example

```java
import java.time.Duration;
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.api.AgentTablesApi;
import com.firefly.flyquery.model.PaginatedSnapshotRead;
import org.springframework.web.reactive.function.client.WebClientResponseException;

public class Example {
    public static void main(String[] args) {
        ApiClient client = new ApiClient();
        client.setBasePath(System.getenv("FLYQUERY_URL"));
        client.addDefaultHeader("X-Tenant-Id", System.getenv("FLYQUERY_TENANT_ID"));
        client.addDefaultHeader("X-Workspace-Id", System.getenv("FLYQUERY_WORKSPACE_ID"));
        AgentTablesApi api = new AgentTablesApi(client);
        String token = System.getenv("FLYQUERY_AGENT_TOKEN");
        String tableId = System.getenv("FLYQUERY_TABLE_ID");
        try {
            PaginatedSnapshotRead page = api.listSnapshots(tableId, token, null).block(Duration.ofSeconds(15));
            if (page == null) throw new IllegalStateException("The API returned no page");
            System.out.println(page.getItems());
        } catch (WebClientResponseException e) {
            System.err.println("HTTP " + e.getStatusCode());
            throw e;
        }
    }
}
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **tableId** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**PaginatedSnapshotRead**](PaginatedSnapshotRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |


## listTables

> Mono<PaginatedTableRead> listTables(datasetId, xAgentToken, xCorrelationId)



### Example

```java
import java.time.Duration;
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.api.AgentTablesApi;
import com.firefly.flyquery.model.PaginatedTableRead;
import org.springframework.web.reactive.function.client.WebClientResponseException;

public class Example {
    public static void main(String[] args) {
        ApiClient client = new ApiClient();
        client.setBasePath(System.getenv("FLYQUERY_URL"));
        client.addDefaultHeader("X-Tenant-Id", System.getenv("FLYQUERY_TENANT_ID"));
        client.addDefaultHeader("X-Workspace-Id", System.getenv("FLYQUERY_WORKSPACE_ID"));
        AgentTablesApi api = new AgentTablesApi(client);
        String token = System.getenv("FLYQUERY_AGENT_TOKEN");
        String datasetId = System.getenv("FLYQUERY_DATASET_ID");
        try {
            PaginatedTableRead page = api.listTables(datasetId, token, null).block(Duration.ofSeconds(15));
            if (page == null) throw new IllegalStateException("The API returned no page");
            System.out.println(page.getItems());
        } catch (WebClientResponseException e) {
            System.err.println("HTTP " + e.getStatusCode());
            throw e;
        }
    }
}
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **datasetId** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**PaginatedTableRead**](PaginatedTableRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |


## searchTables

> Mono<PaginatedTableRead> searchTables(xAgentToken, q, name, datasetId, kind, isActive, limit, offset, xCorrelationId)



### Example

```java
import java.time.Duration;
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.api.AgentTablesApi;
import com.firefly.flyquery.model.PaginatedTableRead;
import org.springframework.web.reactive.function.client.WebClientResponseException;

public class Example {
    public static void main(String[] args) {
        ApiClient client = new ApiClient();
        client.setBasePath(System.getenv("FLYQUERY_URL"));
        client.addDefaultHeader("X-Tenant-Id", System.getenv("FLYQUERY_TENANT_ID"));
        client.addDefaultHeader("X-Workspace-Id", System.getenv("FLYQUERY_WORKSPACE_ID"));
        AgentTablesApi api = new AgentTablesApi(client);
        String token = System.getenv("FLYQUERY_AGENT_TOKEN");
        String datasetId = System.getenv("FLYQUERY_DATASET_ID");
        try {
            PaginatedTableRead page = api.searchTables(token, null, null, datasetId, null, true, 100, 0, null).block(Duration.ofSeconds(15));
            if (page == null) throw new IllegalStateException("The API returned no page");
            System.out.println(page.getItems());
        } catch (WebClientResponseException e) {
            System.err.println("HTTP " + e.getStatusCode());
            throw e;
        }
    }
}
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **q** | **String**|  | [optional] |
| **name** | **String**|  | [optional] |
| **datasetId** | **String**|  | [optional] |
| **kind** | **String**|  | [optional] |
| **isActive** | **Boolean**|  | [optional] [default to null] |
| **limit** | **Integer**|  | [optional] [default to 100] |
| **offset** | **Integer**|  | [optional] [default to 0] |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**PaginatedTableRead**](PaginatedTableRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |

