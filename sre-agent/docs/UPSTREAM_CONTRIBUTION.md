# Upstream Contribution: Fix Service Port Specification

## Summary
The agent-sandbox controller creates Services for sandboxes but doesn't populate `spec.ports`, even when `containerPort` is specified in the pod template. This prevents routers and other components from connecting to sandboxes via their service DNS names.

## Impact
- Sandbox Router returns 502 Bad Gateway
- Investigations fail with no response
- Affects all deployments (local Kind, production EKS, etc.)

## Root Cause

**File:** `controllers/sandbox_controller.go` (lines 270-286)

The `reconcileService` function creates a Service with selectors and labels, but omits the `Ports` field:

```go
service = &corev1.Service{
    ObjectMeta: metav1.ObjectMeta{
        Name:      sandbox.Name,
        Namespace: sandbox.Namespace,
        Labels: map[string]string{
            sandboxLabel: nameHash,
        },
    },
    Spec: corev1.ServiceSpec{
        ClusterIP: "None",
        Selector: map[string]string{
            sandboxLabel: nameHash,
        },
        // Missing: Ports field!
    },
}
```

## Proposed Fix

Extract ports from the pod template and add them to the service spec:

```go
func (r *SandboxReconciler) reconcileService(ctx context.Context, sandbox *sandboxv1alpha1.Sandbox, nameHash string) (*corev1.Service, error) {
    log := log.FromContext(ctx)
    service := &corev1.Service{}
    if err := r.Get(ctx, types.NamespacedName{Name: sandbox.Name, Namespace: sandbox.Namespace}, service); err != nil {
        if !k8serrors.IsNotFound(err) {
            log.Error(err, "Failed to get Service")
            return nil, fmt.Errorf("Service Get Failed: %w", err)
        }
    } else {
        log.Info("Found Service", "Service.Namespace", service.Namespace, "Service.Name", service.Name)
        return service, nil
    }

    // Extract ports from pod template
    var ports []corev1.ServicePort
    for _, container := range sandbox.Spec.PodTemplate.Spec.Containers {
        for _, port := range container.Ports {
            ports = append(ports, corev1.ServicePort{
                Name:       port.Name,
                Port:       port.ContainerPort,
                Protocol:   port.Protocol,
                TargetPort: intstr.FromInt(int(port.ContainerPort)),
            })
        }
    }

    log.Info("Creating a new Headless Service", "Service.Namespace", sandbox.Namespace, "Service.Name", sandbox.Name)
    service = &corev1.Service{
        ObjectMeta: metav1.ObjectMeta{
            Name:      sandbox.Name,
            Namespace: sandbox.Namespace,
            Labels: map[string]string{
                sandboxLabel: nameHash,
            },
        },
        Spec: corev1.ServiceSpec{
            ClusterIP: "None",
            Selector: map[string]string{
                sandboxLabel: nameHash,
            },
            Ports: ports, // Add this!
        },
    }
    service.SetGroupVersionKind(corev1.SchemeGroupVersion.WithKind("Service"))
    if err := ctrl.SetControllerReference(sandbox, service, r.Scheme); err != nil {
        log.Error(err, "Failed to set controller reference")
        return nil, fmt.Errorf("SetControllerReference for Service failed: %w", err)
    }

    err := r.Create(ctx, service, client.FieldOwner(sandboxControllerFieldOwner))
    if err != nil {
        log.Error(err, "Failed to create", "Service.Namespace", service.Namespace, "Service.Name", service.Name)
        return nil, err
    }

    sandbox.Status.ServiceFQDN = service.Name + "." + service.Namespace + ".svc.cluster.local"
    sandbox.Status.Service = service.Name
    return service, nil
}
```

**Import needed:**
```go
"k8s.io/apimachinery/pkg/util/intstr"
```

## Testing

**Before fix:**
```bash
$ kubectl get svc investigation-thread-xxx -o jsonpath='{.spec.ports}'
[]  # Empty!
```

**After fix:**
```bash
$ kubectl get svc investigation-thread-xxx -o jsonpath='{.spec.ports}'
[{"name":"sandbox","port":8888,"protocol":"TCP","targetPort":8888}]
```

## Reproduction

1. Deploy agent-sandbox controller
2. Create a Sandbox with containerPort specified:
   ```yaml
   apiVersion: agents.x-k8s.io/v1alpha1
   kind: Sandbox
   metadata:
     name: test-sandbox
   spec:
     podTemplate:
       spec:
         containers:
         - name: agent
           image: alpine
           ports:
           - name: http
             containerPort: 8888
   ```
3. Check service: `kubectl get svc test-sandbox -o yaml`
4. Observe: `spec.ports` is missing

## Workaround (Until Fix Merged)

We've implemented a lightweight Kubernetes deployment that watches for services with missing ports and patches them automatically:

- **Repository:** https://github.com/incidentfox/mono-repo/blob/interrupt/sre-agent/k8s/service-patcher.yaml
- **Resources:** 10m CPU, 32Mi RAM
- **Functionality:** Polls every 5 seconds and patches services

This workaround works but shouldn't be necessary once this fix is upstream.

## PR Checklist

- [ ] Fork kubernetes-sigs/agent-sandbox
- [ ] Create branch: `fix/service-port-spec`
- [ ] Apply fix to `controllers/sandbox_controller.go`
- [ ] Add unit test for port extraction
- [ ] Run existing tests: `make test`
- [ ] Test with real Sandbox deployment
- [ ] Open PR with description above
- [ ] Reference this issue/discussion

## References

- Agent-sandbox repo: https://github.com/kubernetes-sigs/agent-sandbox
- Controller code: `controllers/sandbox_controller.go`
- API types: `api/v1alpha1/sandbox_types.go`

## Contact

Feel free to mention this was discovered during production deployment of AI agent sandboxes at IncidentFox.

