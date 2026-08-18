package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strings"

	madmin "github.com/minio/madmin-go/v3"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

type policyObservation struct {
	Event    string         `json:"event"`
	Result   string         `json:"result"`
	Observed map[string]any `json:"observed"`
}

func requiredEnv(name string) (string, error) {
	value := os.Getenv(name)
	if value == "" {
		return "", fmt.Errorf("required environment variable %s is empty", name)
	}
	return value, nil
}

// normalizePolicy canonicalises an IAM policy document so that comparison is SEMANTIC, not
// textual. MinIO rewrites what it stores: measured 2026-08-18, a reviewed `"Resource": "arn:..."`
// scalar comes back as `"Resource": ["arn:..."]`. A byte comparison of a JSON round-trip therefore
// reports a difference between two identical policies — which it did, aborting provisioning with
// "effective MinIO policy document differs from reviewed policy" on a policy that was correct.
//
// Coercing the list-valued fields to sorted arrays keeps the check strong: a real widening (an
// added s3:PutObject, a broadened Resource, a dropped Condition) still differs, because only
// scalar-vs-single-element-array and key order are neutralised.
func normalizePolicy(raw []byte) ([]byte, error) {
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, fmt.Errorf("decode policy document: %w", err)
	}
	statements, _ := doc["Statement"].([]any)
	for _, entry := range statements {
		statement, ok := entry.(map[string]any)
		if !ok {
			continue
		}
		for _, field := range []string{"Action", "Resource", "NotAction", "NotResource"} {
			value, present := statement[field]
			if !present {
				continue
			}
			switch typed := value.(type) {
			case string:
				statement[field] = []any{typed}
			case []any:
				items := make([]string, 0, len(typed))
				for _, item := range typed {
					items = append(items, fmt.Sprint(item))
				}
				sort.Strings(items)
				coerced := make([]any, len(items))
				for i, item := range items {
					coerced[i] = item
				}
				statement[field] = coerced
			}
		}
	}
	// Go's encoder sorts map keys, so marshalling here also neutralises key order.
	return json.Marshal(doc)
}

func verifyPolicyDocument(ctx context.Context, client *madmin.AdminClient, policyName string) (string, error) {
	expectedRaw, err := io.ReadAll(os.Stdin)
	if err != nil {
		return "", fmt.Errorf("read expected policy document: %w", err)
	}
	expected, err := normalizePolicy(expectedRaw)
	if err != nil {
		return "", err
	}
	info, err := client.InfoCannedPolicyV2(ctx, policyName)
	if err != nil {
		return "", fmt.Errorf("read effective MinIO policy document: %w", err)
	}
	actual, err := normalizePolicy(info.Policy)
	if err != nil {
		return "", fmt.Errorf("normalize effective MinIO policy document: %w", err)
	}
	if !bytes.Equal(actual, expected) {
		return "", fmt.Errorf("effective MinIO policy document differs from reviewed policy\n  effective: %s\n  reviewed : %s",
			redactSecrets(string(actual)), redactSecrets(string(expected)))
	}
	digest := sha256.Sum256(expected)
	return fmt.Sprintf("sha256:%x", digest), nil
}

func run() (*policyObservation, error) {
	action := os.Getenv("MINIO_MANAGED_ACTION")
	if action == "" {
		action = "ensure"
	}
	endpointValue, err := requiredEnv("MINIO_ENDPOINT")
	if err != nil {
		return nil, err
	}
	rootUser, err := requiredEnv("MINIO_ROOT_USER")
	if err != nil {
		return nil, err
	}
	rootPassword, err := requiredEnv("MINIO_ROOT_PASSWORD")
	if err != nil {
		return nil, err
	}
	managedUser, err := requiredEnv("MINIO_MANAGED_USER")
	if err != nil {
		return nil, err
	}
	policyName, err := requiredEnv("MINIO_POLICY_NAME")
	if err != nil {
		return nil, err
	}
	caPath, err := requiredEnv("MINIO_CA_PATH")
	if err != nil {
		return nil, err
	}

	endpoint, err := url.Parse(endpointValue)
	if err != nil || endpoint.Scheme != "https" || endpoint.Host == "" || endpoint.Path != "" {
		return nil, fmt.Errorf("MINIO_ENDPOINT must be an origin-only https URL")
	}
	if endpoint.RawQuery != "" || endpoint.Fragment != "" || endpoint.User != nil {
		return nil, fmt.Errorf("MINIO_ENDPOINT must not contain credentials, query, or fragment")
	}
	caPEM, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("read CA: %w", err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("CA file contained no PEM certificate")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: roots}
	client, err := madmin.NewWithOptions(endpoint.Host, &madmin.Options{
		Creds:     credentials.NewStaticV4(rootUser, rootPassword, ""),
		Secure:    true,
		Transport: transport,
	})
	if err != nil {
		return nil, fmt.Errorf("create admin client: %w", err)
	}
	if strings.ContainsAny(managedUser, "\r\n") || strings.ContainsAny(policyName, "\r\n") {
		return nil, fmt.Errorf("managed user and policy name must be single-line values")
	}
	ctx := context.Background()
	if action == "delete" {
		if err := client.RemoveUser(ctx, managedUser); err != nil {
			return nil, fmt.Errorf("remove managed MinIO user: %w", err)
		}
		return nil, nil
	}
	if action != "ensure" && action != "verify" {
		return nil, fmt.Errorf("MINIO_MANAGED_ACTION must be ensure, verify, or delete")
	}
	policySubject, err := requiredEnv("MINIO_POLICY_SUBJECT")
	if err != nil {
		return nil, err
	}
	if action == "verify" {
		info, err := client.GetUserInfo(ctx, managedUser)
		if err != nil {
			return nil, fmt.Errorf("verify managed MinIO user: %w", err)
		}
		if info.PolicyName != policyName {
			return nil, fmt.Errorf("managed MinIO policy association is not effective")
		}
		digest, err := verifyPolicyDocument(ctx, client, policyName)
		if err != nil {
			return nil, err
		}
		return &policyObservation{Event: "effective-policy", Result: "PASS", Observed: map[string]any{
			"subject": policySubject, "policyName": policyName, "policySha256": digest,
		}}, nil
	}
	managedSecret, err := requiredEnv("MINIO_MANAGED_SECRET")
	if err != nil {
		return nil, err
	}
	request := madmin.AddOrUpdateUserReq{
		SecretKey: managedSecret,
		Policy:    policyName,
		Status:    madmin.AccountEnabled,
	}
	if err := client.SetUserReq(ctx, managedUser, request); err != nil {
		return nil, fmt.Errorf("set managed MinIO user: %w", err)
	}
	// The 2025 MinIO server accepts Policy in SetUserReq but does not make that
	// association effective for an existing user. Reconcile the association via
	// the server's policy endpoint, then read it back before reporting success.
	if err := client.SetPolicy(ctx, policyName, managedUser, false); err != nil {
		return nil, fmt.Errorf("set managed MinIO policy: %w", err)
	}
	info, err := client.GetUserInfo(ctx, managedUser)
	if err != nil {
		return nil, fmt.Errorf("verify managed MinIO user: %w", err)
	}
	if info.PolicyName != policyName {
		return nil, fmt.Errorf("managed MinIO policy association did not become effective")
	}
	digest, err := verifyPolicyDocument(ctx, client, policyName)
	if err != nil {
		return nil, err
	}
	return &policyObservation{Event: "effective-policy", Result: "PASS", Observed: map[string]any{
		"subject": policySubject, "policyName": policyName, "policySha256": digest,
	}}, nil
}

// redactSecrets removes credential-looking material from an error string so the cause can be
// printed safely. It is deliberately blunt: long high-entropy runs, URL userinfo, and values
// following credential markers are replaced rather than trimmed to a guess at their length.
func redactSecrets(s string) string {
	s = regexp.MustCompile(`([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@`).ReplaceAllString(s, "${1}[redacted]@")
	s = regexp.MustCompile(`(?i)(secret|password|accesskey|access_key|secretkey|secret_key|token)([\s:=]+)\S+`).ReplaceAllString(s, "${1}${2}[redacted]")
	s = regexp.MustCompile(`\b[A-Za-z0-9+/]{32,}={0,2}\b`).ReplaceAllString(s, "[redacted]")
	return s
}

func main() {
	observation, err := run()
	if err != nil {
		// Print the real error, with any credential-looking token redacted. Printing only a
		// generic sentence destroys the diagnostic — the same failure this drill's own header
		// warns about, and it cost a rebuild run to rediscover. Secrets are the reason for
		// caution, not a reason to discard the cause: redact, do not swallow.
		fmt.Fprintf(os.Stderr, "ERROR: MinIO user provisioning failed: %s\n", redactSecrets(err.Error()))
		os.Exit(1)
	}
	if observation == nil {
		fmt.Println("PASS: MinIO managed identity action completed")
		return
	}
	encoded, err := json.Marshal(observation)
	if err != nil {
		fmt.Fprintln(os.Stderr, "ERROR: MinIO policy observation encoding failed")
		os.Exit(1)
	}
	fmt.Println(string(encoded))
}
