// Copyright 2021 Vectorized, Inc.
//
// Use of this software is governed by the Business Source License
// included in the file licenses/BSL.md
//
// As of the Change Date specified in that file, in accordance with
// the Business Source License, use of this software will be governed
// by the Apache License, Version 2.0

// Package resources contains reconciliation logic for redpanda.vectorized.io CRD
package resources

import (
	"context"
	"fmt"

	"github.com/go-logr/logr"
	redpandav1alpha1 "github.com/vectorizedio/redpanda/src/go/k8s/apis/redpanda/v1alpha1"
	"github.com/vectorizedio/redpanda/src/go/k8s/pkg/labels"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	k8sclient "sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

var _ Resource = &ServiceResource{}

// ServiceResource is part of the reconciliation of redpanda.vectorized.io CRD
// focusing on the connectivity management of redpanda cluster
type ServiceResource struct {
	k8sclient.Client
	scheme		*runtime.Scheme
	pandaCluster	*redpandav1alpha1.Cluster
	logger		logr.Logger
}

// NewService creates ServiceResource
func NewService(
	client k8sclient.Client,
	pandaCluster *redpandav1alpha1.Cluster,
	scheme *runtime.Scheme,
	logger logr.Logger,
) *ServiceResource {
	return &ServiceResource{
		client, scheme, pandaCluster, logger.WithValues("Kind", serviceKind()),
	}
}

// Ensure will manage kubernetes v1.Service for redpanda.vectorized.io custom resource
//nolint:dupl // we expect this to not be duplicated when more logic is added
func (r *ServiceResource) Ensure(ctx context.Context) error {
	var svc corev1.Service

	err := r.Get(ctx, r.Key(), &svc)
	if err != nil && !errors.IsNotFound(err) {
		return err
	}

	if errors.IsNotFound(err) {
		r.logger.Info(fmt.Sprintf("Service %s does not exist, going to create one", r.Key().Name))

		obj, err := r.Obj()
		if err != nil {
			return err
		}

		return r.Create(ctx, obj)
	}

	return nil
}

// Obj returns resource managed client.Object
func (r *ServiceResource) Obj() (k8sclient.Object, error) {
	objLabels := labels.ForCluster(r.pandaCluster)
	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Namespace:	r.Key().Namespace,
			Name:		r.Key().Name,
			Labels:		objLabels,
		},
		Spec: corev1.ServiceSpec{
			ClusterIP:	corev1.ClusterIPNone,
			Ports: []corev1.ServicePort{
				{
					Name:		"kafka-tcp",
					Protocol:	corev1.ProtocolTCP,
					Port:		int32(r.pandaCluster.Spec.Configuration.KafkaAPI.Port),
					TargetPort:	intstr.FromInt(r.pandaCluster.Spec.Configuration.KafkaAPI.Port),
				},
			},
			Selector:	objLabels.AsAPISelector().MatchLabels,
		},
	}

	err := controllerutil.SetControllerReference(r.pandaCluster, svc, r.scheme)
	if err != nil {
		return nil, err
	}

	return svc, nil
}

// Key returns namespace/name object that is used to identify object.
// For reference please visit types.NamespacedName docs in k8s.io/apimachinery
func (r *ServiceResource) Key() types.NamespacedName {
	return types.NamespacedName{Name: r.pandaCluster.Name, Namespace: r.pandaCluster.Namespace}
}

// Kind returns v1.Service kind
func (r *ServiceResource) Kind() string {
	return serviceKind()
}

func serviceKind() string {
	var svc corev1.Service
	return svc.Kind
}

// HeadlessServiceFQDN returns fully qualified domain name for headless service.
// It can be used to communicate between namespaces if the network policy
// allows it.
func (r *ServiceResource) HeadlessServiceFQDN() string {
	// TODO Retrieve cluster domain dynamically and remove hardcoded cluster.local
	return fmt.Sprintf("%s%c%s.svc.cluster.local",
		r.Key().Name,
		'.',
		r.Key().Namespace)
}
