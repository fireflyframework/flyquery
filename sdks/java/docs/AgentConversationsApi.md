# AgentConversationsApi

All URIs are relative to *http://localhost*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**create**](AgentConversationsApi.md#create) | **POST** /api/v1/agent/conversations | Create a conversation owned by the calling agent. |
| [**listConversations**](AgentConversationsApi.md#listConversations) | **GET** /api/v1/agent/conversations | List conversations for the agent&#39;s workspace (newest first). |
| [**postTurn**](AgentConversationsApi.md#postTurn) | **POST** /api/v1/agent/conversations/{conversation_id}/turn | Run a drill-down turn through the full query pipeline. |
| [**read**](AgentConversationsApi.md#read) | **GET** /api/v1/agent/conversations/{conversation_id} | Fetch a conversation with its turns. |



## create

> ConversationRead create(xAgentToken, conversationCreate, xCorrelationId, idempotencyKey)

Create a conversation owned by the calling agent.

Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required). A retried create otherwise allocates duplicate empty conversations the agent has no way to clean up.

### Example

```java
// Import classes:
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.ApiException;
import com.firefly.flyquery.Configuration;
import com.firefly.flyquery.auth.*;
import com.firefly.flyquery.models.*;
import com.firefly.flyquery.api.AgentConversationsApi;

public class Example {
    public static void main(String[] args) {
        ApiClient defaultClient = Configuration.getDefaultApiClient();
        defaultClient.setBasePath("http://localhost");
        
        // Configure API key authorization: AgentToken
        ApiKeyAuth AgentToken = (ApiKeyAuth) defaultClient.getAuthentication("AgentToken");
        AgentToken.setApiKey("YOUR API KEY");
        // Uncomment the following line to set a prefix for the API key, e.g. "Token" (defaults to null)
        //AgentToken.setApiKeyPrefix("Token");

        AgentConversationsApi apiInstance = new AgentConversationsApi(defaultClient);
        String xAgentToken = "fqt_live_aBcDeF1234567890aBcDeF1234567890"; // String | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
        ConversationCreate conversationCreate = new ConversationCreate(); // ConversationCreate | 
        UUID xCorrelationId = UUID.fromString("550e8400-e29b-41d4-a716-446655440000"); // UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
        String idempotencyKey = "ingest-2026-05-23-abc123"; // String | Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
        try {
            ConversationRead result = apiInstance.create(xAgentToken, conversationCreate, xCorrelationId, idempotencyKey);
            System.out.println(result);
        } catch (ApiException e) {
            System.err.println("Exception when calling AgentConversationsApi#create");
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
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **conversationCreate** | [**ConversationCreate**](ConversationCreate.md)|  | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |
| **idempotencyKey** | **String**| Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h. | [optional] |

### Return type

[**ConversationRead**](ConversationRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: application/json
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **201** | Successful response |  -  |
| **422** | Validation Error |  -  |


## listConversations

> Mono<PaginatedConversationRead> listConversations(xAgentToken, xCorrelationId)

List conversations for the agent&#39;s workspace (newest first).

### Example

```java
import java.time.Duration;
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.api.AgentConversationsApi;
import com.firefly.flyquery.model.PaginatedConversationRead;
import org.springframework.web.reactive.function.client.WebClientResponseException;

public class Example {
    public static void main(String[] args) {
        ApiClient client = new ApiClient();
        client.setBasePath(System.getenv("FLYQUERY_URL"));
        client.addDefaultHeader("X-Tenant-Id", System.getenv("FLYQUERY_TENANT_ID"));
        client.addDefaultHeader("X-Workspace-Id", System.getenv("FLYQUERY_WORKSPACE_ID"));
        AgentConversationsApi api = new AgentConversationsApi(client);
        String token = System.getenv("FLYQUERY_AGENT_TOKEN");
        try {
            PaginatedConversationRead page = api.listConversations(token, null).block(Duration.ofSeconds(15));
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
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**PaginatedConversationRead**](PaginatedConversationRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |


## postTurn

> AnswerResponse postTurn(conversationId, xAgentToken, conversationTurnRequest, xCorrelationId, idempotencyKey)

Run a drill-down turn through the full query pipeline.

Two scopes are required at the agent layer: &#x60;&#x60;flyquery.conversations:write&#x60;&#x60; (this is a mutating turn write) and the underlying &#x60;&#x60;flyquery.query:read&#x60;&#x60; (the pipeline executes a query). We verify the conversations scope here and delegate the query-tier check to the pipeline&#39;s scope guard.  Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required) -- the 4-agent pipeline is the costliest endpoint in the API.

### Example

```java
// Import classes:
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.ApiException;
import com.firefly.flyquery.Configuration;
import com.firefly.flyquery.auth.*;
import com.firefly.flyquery.models.*;
import com.firefly.flyquery.api.AgentConversationsApi;

public class Example {
    public static void main(String[] args) {
        ApiClient defaultClient = Configuration.getDefaultApiClient();
        defaultClient.setBasePath("http://localhost");
        
        // Configure API key authorization: AgentToken
        ApiKeyAuth AgentToken = (ApiKeyAuth) defaultClient.getAuthentication("AgentToken");
        AgentToken.setApiKey("YOUR API KEY");
        // Uncomment the following line to set a prefix for the API key, e.g. "Token" (defaults to null)
        //AgentToken.setApiKeyPrefix("Token");

        AgentConversationsApi apiInstance = new AgentConversationsApi(defaultClient);
        String conversationId = "conversationId_example"; // String | 
        String xAgentToken = "fqt_live_aBcDeF1234567890aBcDeF1234567890"; // String | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
        ConversationTurnRequest conversationTurnRequest = new ConversationTurnRequest(); // ConversationTurnRequest | 
        UUID xCorrelationId = UUID.fromString("550e8400-e29b-41d4-a716-446655440000"); // UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
        String idempotencyKey = "ingest-2026-05-23-abc123"; // String | Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
        try {
            AnswerResponse result = apiInstance.postTurn(conversationId, xAgentToken, conversationTurnRequest, xCorrelationId, idempotencyKey);
            System.out.println(result);
        } catch (ApiException e) {
            System.err.println("Exception when calling AgentConversationsApi#postTurn");
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
| **conversationId** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **conversationTurnRequest** | [**ConversationTurnRequest**](ConversationTurnRequest.md)|  | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |
| **idempotencyKey** | **String**| Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h. | [optional] |

### Return type

[**AnswerResponse**](AnswerResponse.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: application/json
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |
| **422** | Validation Error |  -  |


## read

> ConversationRead read(conversationId, xAgentToken, xCorrelationId)

Fetch a conversation with its turns.

### Example

```java
// Import classes:
import com.firefly.flyquery.ApiClient;
import com.firefly.flyquery.ApiException;
import com.firefly.flyquery.Configuration;
import com.firefly.flyquery.auth.*;
import com.firefly.flyquery.models.*;
import com.firefly.flyquery.api.AgentConversationsApi;

public class Example {
    public static void main(String[] args) {
        ApiClient defaultClient = Configuration.getDefaultApiClient();
        defaultClient.setBasePath("http://localhost");
        
        // Configure API key authorization: AgentToken
        ApiKeyAuth AgentToken = (ApiKeyAuth) defaultClient.getAuthentication("AgentToken");
        AgentToken.setApiKey("YOUR API KEY");
        // Uncomment the following line to set a prefix for the API key, e.g. "Token" (defaults to null)
        //AgentToken.setApiKeyPrefix("Token");

        AgentConversationsApi apiInstance = new AgentConversationsApi(defaultClient);
        String conversationId = "conversationId_example"; // String | 
        String xAgentToken = "fqt_live_aBcDeF1234567890aBcDeF1234567890"; // String | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
        UUID xCorrelationId = UUID.fromString("550e8400-e29b-41d4-a716-446655440000"); // UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
        try {
            ConversationRead result = apiInstance.read(conversationId, xAgentToken, xCorrelationId);
            System.out.println(result);
        } catch (ApiException e) {
            System.err.println("Exception when calling AgentConversationsApi#read");
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
| **conversationId** | **String**|  | |
| **xAgentToken** | **String**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | |
| **xCorrelationId** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] |

### Return type

[**ConversationRead**](ConversationRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful response |  -  |

