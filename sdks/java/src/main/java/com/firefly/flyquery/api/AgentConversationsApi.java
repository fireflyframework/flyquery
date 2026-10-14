package com.firefly.flyquery.api;

import com.firefly.flyquery.ApiClient;

import com.firefly.flyquery.model.AnswerResponse;
import com.firefly.flyquery.model.ConversationCreate;
import com.firefly.flyquery.model.ConversationRead;
import com.firefly.flyquery.model.ConversationTurnRequest;
import com.firefly.flyquery.model.HTTPValidationError;
import com.firefly.flyquery.model.PaginatedConversationRead;
import java.util.UUID;

import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Arrays;
import java.util.stream.Collectors;

import org.springframework.core.io.FileSystemResource;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.reactive.function.client.WebClient.ResponseSpec;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;

@jakarta.annotation.Generated(value = "org.openapitools.codegen.languages.JavaClientCodegen", date = "2026-10-14T13:20:41.405226-07:00[America/Los_Angeles]", comments = "Generator version: 7.22.0")
public class AgentConversationsApi {
    private ApiClient apiClient;

    public AgentConversationsApi() {
        this(new ApiClient());
    }

    public AgentConversationsApi(ApiClient apiClient) {
        this.apiClient = apiClient;
    }

    public ApiClient getApiClient() {
        return apiClient;
    }

    public void setApiClient(ApiClient apiClient) {
        this.apiClient = apiClient;
    }

    /**
     * Create a conversation owned by the calling agent.
     * Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required). A retried create otherwise allocates duplicate empty conversations the agent has no way to clean up.
     * <p><b>201</b> - Successful response
     * <p><b>422</b> - Validation Error
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param conversationCreate The conversationCreate parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @param idempotencyKey Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
     * @return ConversationRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    private ResponseSpec createRequestCreation(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nonnull ConversationCreate conversationCreate, @jakarta.annotation.Nullable UUID xCorrelationId, @jakarta.annotation.Nullable String idempotencyKey) throws WebClientResponseException {
        Object postBody = conversationCreate;
        // verify the required parameter 'xAgentToken' is set
        if (xAgentToken == null) {
            throw new WebClientResponseException("Missing the required parameter 'xAgentToken' when calling create", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // verify the required parameter 'conversationCreate' is set
        if (conversationCreate == null) {
            throw new WebClientResponseException("Missing the required parameter 'conversationCreate' when calling create", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // create path and map variables
        final Map<String, Object> pathParams = new HashMap<String, Object>();

        final MultiValueMap<String, String> queryParams = new LinkedMultiValueMap<String, String>();
        final HttpHeaders headerParams = new HttpHeaders();
        final MultiValueMap<String, String> cookieParams = new LinkedMultiValueMap<String, String>();
        final MultiValueMap<String, Object> formParams = new LinkedMultiValueMap<String, Object>();

        if (xAgentToken != null)
        headerParams.add("X-Agent-Token", apiClient.parameterToString(xAgentToken));
        if (xCorrelationId != null)
        headerParams.add("X-Correlation-Id", apiClient.parameterToString(xCorrelationId));
        if (idempotencyKey != null)
        headerParams.add("Idempotency-Key", apiClient.parameterToString(idempotencyKey));
        final String[] localVarAccepts = { 
            "application/json"
        };
        final List<MediaType> localVarAccept = apiClient.selectHeaderAccept(localVarAccepts);
        final String[] localVarContentTypes = { 
            "application/json"
        };
        final MediaType localVarContentType = apiClient.selectHeaderContentType(localVarContentTypes);

        String[] localVarAuthNames = new String[] { "AgentToken" };

        ParameterizedTypeReference<ConversationRead> localVarReturnType = new ParameterizedTypeReference<ConversationRead>() {};
        return apiClient.invokeAPI("/api/v1/agent/conversations", HttpMethod.POST, pathParams, queryParams, postBody, headerParams, cookieParams, formParams, localVarAccept, localVarContentType, localVarAuthNames, localVarReturnType);
    }

    /**
     * Create a conversation owned by the calling agent.
     * Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required). A retried create otherwise allocates duplicate empty conversations the agent has no way to clean up.
     * <p><b>201</b> - Successful response
     * <p><b>422</b> - Validation Error
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param conversationCreate The conversationCreate parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @param idempotencyKey Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
     * @return ConversationRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ConversationRead> create(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nonnull ConversationCreate conversationCreate, @jakarta.annotation.Nullable UUID xCorrelationId, @jakarta.annotation.Nullable String idempotencyKey) throws WebClientResponseException {
        ParameterizedTypeReference<ConversationRead> localVarReturnType = new ParameterizedTypeReference<ConversationRead>() {};
        return createRequestCreation(xAgentToken, conversationCreate, xCorrelationId, idempotencyKey).bodyToMono(localVarReturnType);
    }

    /**
     * Create a conversation owned by the calling agent.
     * Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required). A retried create otherwise allocates duplicate empty conversations the agent has no way to clean up.
     * <p><b>201</b> - Successful response
     * <p><b>422</b> - Validation Error
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param conversationCreate The conversationCreate parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @param idempotencyKey Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
     * @return ResponseEntity&lt;ConversationRead&gt;
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ResponseEntity<ConversationRead>> createWithHttpInfo(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nonnull ConversationCreate conversationCreate, @jakarta.annotation.Nullable UUID xCorrelationId, @jakarta.annotation.Nullable String idempotencyKey) throws WebClientResponseException {
        ParameterizedTypeReference<ConversationRead> localVarReturnType = new ParameterizedTypeReference<ConversationRead>() {};
        return createRequestCreation(xAgentToken, conversationCreate, xCorrelationId, idempotencyKey).toEntity(localVarReturnType);
    }

    /**
     * Create a conversation owned by the calling agent.
     * Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required). A retried create otherwise allocates duplicate empty conversations the agent has no way to clean up.
     * <p><b>201</b> - Successful response
     * <p><b>422</b> - Validation Error
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param conversationCreate The conversationCreate parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @param idempotencyKey Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
     * @return ResponseSpec
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public ResponseSpec createWithResponseSpec(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nonnull ConversationCreate conversationCreate, @jakarta.annotation.Nullable UUID xCorrelationId, @jakarta.annotation.Nullable String idempotencyKey) throws WebClientResponseException {
        return createRequestCreation(xAgentToken, conversationCreate, xCorrelationId, idempotencyKey);
    }

    /**
     * List conversations for the agent&#39;s workspace (newest first).
     * 
     * <p><b>200</b> - Successful response
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return PaginatedConversationRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    private ResponseSpec listConversationsRequestCreation(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        Object postBody = null;
        // verify the required parameter 'xAgentToken' is set
        if (xAgentToken == null) {
            throw new WebClientResponseException("Missing the required parameter 'xAgentToken' when calling listConversations", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // create path and map variables
        final Map<String, Object> pathParams = new HashMap<String, Object>();

        final MultiValueMap<String, String> queryParams = new LinkedMultiValueMap<String, String>();
        final HttpHeaders headerParams = new HttpHeaders();
        final MultiValueMap<String, String> cookieParams = new LinkedMultiValueMap<String, String>();
        final MultiValueMap<String, Object> formParams = new LinkedMultiValueMap<String, Object>();

        if (xAgentToken != null)
        headerParams.add("X-Agent-Token", apiClient.parameterToString(xAgentToken));
        if (xCorrelationId != null)
        headerParams.add("X-Correlation-Id", apiClient.parameterToString(xCorrelationId));
        final String[] localVarAccepts = {
            "application/json"
        };
        final List<MediaType> localVarAccept = apiClient.selectHeaderAccept(localVarAccepts);
        final String[] localVarContentTypes = { };
        final MediaType localVarContentType = apiClient.selectHeaderContentType(localVarContentTypes);

        String[] localVarAuthNames = new String[] { "AgentToken" };

        ParameterizedTypeReference<PaginatedConversationRead> localVarReturnType = new ParameterizedTypeReference<PaginatedConversationRead>() {};
        return apiClient.invokeAPI("/api/v1/agent/conversations", HttpMethod.GET, pathParams, queryParams, postBody, headerParams, cookieParams, formParams, localVarAccept, localVarContentType, localVarAuthNames, localVarReturnType);
    }

    /**
     * List conversations for the agent&#39;s workspace (newest first).
     * 
     * <p><b>200</b> - Successful response
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return PaginatedConversationRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<PaginatedConversationRead> listConversations(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<PaginatedConversationRead> localVarReturnType = new ParameterizedTypeReference<PaginatedConversationRead>() {};
        return listConversationsRequestCreation(xAgentToken, xCorrelationId).bodyToMono(localVarReturnType);
    }

    /**
     * List conversations for the agent&#39;s workspace (newest first).
     * 
     * <p><b>200</b> - Successful response
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseEntity&lt;PaginatedConversationRead&gt;
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ResponseEntity<PaginatedConversationRead>> listConversationsWithHttpInfo(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<PaginatedConversationRead> localVarReturnType = new ParameterizedTypeReference<PaginatedConversationRead>() {};
        return listConversationsRequestCreation(xAgentToken, xCorrelationId).toEntity(localVarReturnType);
    }

    /**
     * List conversations for the agent&#39;s workspace (newest first).
     * 
     * <p><b>200</b> - Successful response
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseSpec
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public ResponseSpec listConversationsWithResponseSpec(@jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        return listConversationsRequestCreation(xAgentToken, xCorrelationId);
    }

    /**
     * Run a drill-down turn through the full query pipeline.
     * Two scopes are required at the agent layer: &#x60;&#x60;flyquery.conversations:write&#x60;&#x60; (this is a mutating turn write) and the underlying &#x60;&#x60;flyquery.query:read&#x60;&#x60; (the pipeline executes a query). We verify the conversations scope here and delegate the query-tier check to the pipeline&#39;s scope guard.  Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required) -- the 4-agent pipeline is the costliest endpoint in the API.
     * <p><b>200</b> - Successful response
     * <p><b>422</b> - Validation Error
     * @param conversationId The conversationId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param conversationTurnRequest The conversationTurnRequest parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @param idempotencyKey Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
     * @return AnswerResponse
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    private ResponseSpec postTurnRequestCreation(@jakarta.annotation.Nonnull String conversationId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nonnull ConversationTurnRequest conversationTurnRequest, @jakarta.annotation.Nullable UUID xCorrelationId, @jakarta.annotation.Nullable String idempotencyKey) throws WebClientResponseException {
        Object postBody = conversationTurnRequest;
        // verify the required parameter 'conversationId' is set
        if (conversationId == null) {
            throw new WebClientResponseException("Missing the required parameter 'conversationId' when calling postTurn", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // verify the required parameter 'xAgentToken' is set
        if (xAgentToken == null) {
            throw new WebClientResponseException("Missing the required parameter 'xAgentToken' when calling postTurn", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // verify the required parameter 'conversationTurnRequest' is set
        if (conversationTurnRequest == null) {
            throw new WebClientResponseException("Missing the required parameter 'conversationTurnRequest' when calling postTurn", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // create path and map variables
        final Map<String, Object> pathParams = new HashMap<String, Object>();

        pathParams.put("conversation_id", conversationId);

        final MultiValueMap<String, String> queryParams = new LinkedMultiValueMap<String, String>();
        final HttpHeaders headerParams = new HttpHeaders();
        final MultiValueMap<String, String> cookieParams = new LinkedMultiValueMap<String, String>();
        final MultiValueMap<String, Object> formParams = new LinkedMultiValueMap<String, Object>();

        if (xAgentToken != null)
        headerParams.add("X-Agent-Token", apiClient.parameterToString(xAgentToken));
        if (xCorrelationId != null)
        headerParams.add("X-Correlation-Id", apiClient.parameterToString(xCorrelationId));
        if (idempotencyKey != null)
        headerParams.add("Idempotency-Key", apiClient.parameterToString(idempotencyKey));
        final String[] localVarAccepts = { 
            "application/json"
        };
        final List<MediaType> localVarAccept = apiClient.selectHeaderAccept(localVarAccepts);
        final String[] localVarContentTypes = { 
            "application/json"
        };
        final MediaType localVarContentType = apiClient.selectHeaderContentType(localVarContentTypes);

        String[] localVarAuthNames = new String[] { "AgentToken" };

        ParameterizedTypeReference<AnswerResponse> localVarReturnType = new ParameterizedTypeReference<AnswerResponse>() {};
        return apiClient.invokeAPI("/api/v1/agent/conversations/{conversation_id}/turn", HttpMethod.POST, pathParams, queryParams, postBody, headerParams, cookieParams, formParams, localVarAccept, localVarContentType, localVarAuthNames, localVarReturnType);
    }

    /**
     * Run a drill-down turn through the full query pipeline.
     * Two scopes are required at the agent layer: &#x60;&#x60;flyquery.conversations:write&#x60;&#x60; (this is a mutating turn write) and the underlying &#x60;&#x60;flyquery.query:read&#x60;&#x60; (the pipeline executes a query). We verify the conversations scope here and delegate the query-tier check to the pipeline&#39;s scope guard.  Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required) -- the 4-agent pipeline is the costliest endpoint in the API.
     * <p><b>200</b> - Successful response
     * <p><b>422</b> - Validation Error
     * @param conversationId The conversationId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param conversationTurnRequest The conversationTurnRequest parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @param idempotencyKey Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
     * @return AnswerResponse
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<AnswerResponse> postTurn(@jakarta.annotation.Nonnull String conversationId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nonnull ConversationTurnRequest conversationTurnRequest, @jakarta.annotation.Nullable UUID xCorrelationId, @jakarta.annotation.Nullable String idempotencyKey) throws WebClientResponseException {
        ParameterizedTypeReference<AnswerResponse> localVarReturnType = new ParameterizedTypeReference<AnswerResponse>() {};
        return postTurnRequestCreation(conversationId, xAgentToken, conversationTurnRequest, xCorrelationId, idempotencyKey).bodyToMono(localVarReturnType);
    }

    /**
     * Run a drill-down turn through the full query pipeline.
     * Two scopes are required at the agent layer: &#x60;&#x60;flyquery.conversations:write&#x60;&#x60; (this is a mutating turn write) and the underlying &#x60;&#x60;flyquery.query:read&#x60;&#x60; (the pipeline executes a query). We verify the conversations scope here and delegate the query-tier check to the pipeline&#39;s scope guard.  Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required) -- the 4-agent pipeline is the costliest endpoint in the API.
     * <p><b>200</b> - Successful response
     * <p><b>422</b> - Validation Error
     * @param conversationId The conversationId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param conversationTurnRequest The conversationTurnRequest parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @param idempotencyKey Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
     * @return ResponseEntity&lt;AnswerResponse&gt;
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ResponseEntity<AnswerResponse>> postTurnWithHttpInfo(@jakarta.annotation.Nonnull String conversationId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nonnull ConversationTurnRequest conversationTurnRequest, @jakarta.annotation.Nullable UUID xCorrelationId, @jakarta.annotation.Nullable String idempotencyKey) throws WebClientResponseException {
        ParameterizedTypeReference<AnswerResponse> localVarReturnType = new ParameterizedTypeReference<AnswerResponse>() {};
        return postTurnRequestCreation(conversationId, xAgentToken, conversationTurnRequest, xCorrelationId, idempotencyKey).toEntity(localVarReturnType);
    }

    /**
     * Run a drill-down turn through the full query pipeline.
     * Two scopes are required at the agent layer: &#x60;&#x60;flyquery.conversations:write&#x60;&#x60; (this is a mutating turn write) and the underlying &#x60;&#x60;flyquery.query:read&#x60;&#x60; (the pipeline executes a query). We verify the conversations scope here and delegate the query-tier check to the pipeline&#39;s scope guard.  Replay-dedup&#39;d via &#x60;&#x60;Idempotency-Key&#x60;&#x60; (required) -- the 4-agent pipeline is the costliest endpoint in the API.
     * <p><b>200</b> - Successful response
     * <p><b>422</b> - Validation Error
     * @param conversationId The conversationId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param conversationTurnRequest The conversationTurnRequest parameter
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @param idempotencyKey Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h.
     * @return ResponseSpec
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public ResponseSpec postTurnWithResponseSpec(@jakarta.annotation.Nonnull String conversationId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nonnull ConversationTurnRequest conversationTurnRequest, @jakarta.annotation.Nullable UUID xCorrelationId, @jakarta.annotation.Nullable String idempotencyKey) throws WebClientResponseException {
        return postTurnRequestCreation(conversationId, xAgentToken, conversationTurnRequest, xCorrelationId, idempotencyKey);
    }

    /**
     * Fetch a conversation with its turns.
     * 
     * <p><b>200</b> - Successful response
     * @param conversationId The conversationId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ConversationRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    private ResponseSpec readRequestCreation(@jakarta.annotation.Nullable String conversationId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        Object postBody = null;
        // verify the required parameter 'conversationId' is set
        if (conversationId == null) {
            throw new WebClientResponseException("Missing the required parameter 'conversationId' when calling read", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // verify the required parameter 'xAgentToken' is set
        if (xAgentToken == null) {
            throw new WebClientResponseException("Missing the required parameter 'xAgentToken' when calling read", HttpStatus.BAD_REQUEST.value(), HttpStatus.BAD_REQUEST.getReasonPhrase(), null, null, null);
        }
        // create path and map variables
        final Map<String, Object> pathParams = new HashMap<String, Object>();

        pathParams.put("conversation_id", conversationId);

        final MultiValueMap<String, String> queryParams = new LinkedMultiValueMap<String, String>();
        final HttpHeaders headerParams = new HttpHeaders();
        final MultiValueMap<String, String> cookieParams = new LinkedMultiValueMap<String, String>();
        final MultiValueMap<String, Object> formParams = new LinkedMultiValueMap<String, Object>();

        if (xAgentToken != null)
        headerParams.add("X-Agent-Token", apiClient.parameterToString(xAgentToken));
        if (xCorrelationId != null)
        headerParams.add("X-Correlation-Id", apiClient.parameterToString(xCorrelationId));
        final String[] localVarAccepts = { 
            "application/json"
        };
        final List<MediaType> localVarAccept = apiClient.selectHeaderAccept(localVarAccepts);
        final String[] localVarContentTypes = { };
        final MediaType localVarContentType = apiClient.selectHeaderContentType(localVarContentTypes);

        String[] localVarAuthNames = new String[] { "AgentToken" };

        ParameterizedTypeReference<ConversationRead> localVarReturnType = new ParameterizedTypeReference<ConversationRead>() {};
        return apiClient.invokeAPI("/api/v1/agent/conversations/{conversation_id}", HttpMethod.GET, pathParams, queryParams, postBody, headerParams, cookieParams, formParams, localVarAccept, localVarContentType, localVarAuthNames, localVarReturnType);
    }

    /**
     * Fetch a conversation with its turns.
     * 
     * <p><b>200</b> - Successful response
     * @param conversationId The conversationId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ConversationRead
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ConversationRead> read(@jakarta.annotation.Nullable String conversationId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<ConversationRead> localVarReturnType = new ParameterizedTypeReference<ConversationRead>() {};
        return readRequestCreation(conversationId, xAgentToken, xCorrelationId).bodyToMono(localVarReturnType);
    }

    /**
     * Fetch a conversation with its turns.
     * 
     * <p><b>200</b> - Successful response
     * @param conversationId The conversationId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseEntity&lt;ConversationRead&gt;
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public Mono<ResponseEntity<ConversationRead>> readWithHttpInfo(@jakarta.annotation.Nullable String conversationId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        ParameterizedTypeReference<ConversationRead> localVarReturnType = new ParameterizedTypeReference<ConversationRead>() {};
        return readRequestCreation(conversationId, xAgentToken, xCorrelationId).toEntity(localVarReturnType);
    }

    /**
     * Fetch a conversation with its turns.
     * 
     * <p><b>200</b> - Successful response
     * @param conversationId The conversationId parameter
     * @param xAgentToken Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;.
     * @param xCorrelationId Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header.
     * @return ResponseSpec
     * @throws WebClientResponseException if an error occurs while attempting to invoke the API
     */
    public ResponseSpec readWithResponseSpec(@jakarta.annotation.Nullable String conversationId, @jakarta.annotation.Nonnull String xAgentToken, @jakarta.annotation.Nullable UUID xCorrelationId) throws WebClientResponseException {
        return readRequestCreation(conversationId, xAgentToken, xCorrelationId);
    }
}
