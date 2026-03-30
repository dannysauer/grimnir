---
# ansible/deploy.yaml
# Deploys the CSI stack to a Kubernetes cluster via Helm.
#
# Prerequisites on the control node:
#   pip install kubernetes ansible
#   ansible-galaxy collection install kubernetes.core
#
# Usage:
#   ansible-playbook deploy.yaml \
#     -e db_url="postgresql://user:pass@host:5432/csi" \
#     -e registry="your-registry.example.com" \
#     -e aggregator_lb_ip="192.168.1.50"   # optional, MetalLB pin

- name: Deploy CSI Localization Stack
  hosts: localhost
  connection: local
  gather_facts: false

  vars:
    release_name:     csi
    namespace:        csi
    chart_path:       "{{ playbook_dir }}/../helm/csi"
    registry:         "your-registry.example.com"  # override via -e
    image_tag:        "latest"
    aggregator_lb_ip: ""    # set to pin MetalLB IP

  tasks:

    - name: Ensure namespace exists
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: v1
          kind: Namespace
          metadata:
            name: "{{ namespace }}"

    - name: Build aggregator image
      community.docker.docker_image:
        build:
          path: "{{ playbook_dir }}/../aggregator"
        name: "{{ registry }}/csi-aggregator"
        tag: "{{ image_tag }}"
        source: build
        push: true

    - name: Build backend image
      community.docker.docker_image:
        build:
          path: "{{ playbook_dir }}/../backend"
        name: "{{ registry }}/csi-backend"
        tag: "{{ image_tag }}"
        source: build
        push: true

    - name: Deploy Helm chart
      kubernetes.core.helm:
        name:            "{{ release_name }}"
        chart_ref:       "{{ chart_path }}"
        release_namespace: "{{ namespace }}"
        create_namespace: true
        wait: true
        values:
          image:
            aggregator:
              repository: "{{ registry }}/csi-aggregator"
              tag:        "{{ image_tag }}"
            backend:
              repository: "{{ registry }}/csi-backend"
              tag:        "{{ image_tag }}"
          database:
            url: "{{ db_url }}"
          service:
            aggregatorType: "{{ 'LoadBalancer' if aggregator_lb_ip else 'NodePort' }}"

    - name: Wait for aggregator rollout
      kubernetes.core.k8s_info:
        api_version: apps/v1
        kind: Deployment
        name: "{{ release_name }}-aggregator"
        namespace: "{{ namespace }}"
        wait: true
        wait_condition:
          type: Available
          status: "True"
        wait_timeout: 120

    - name: Wait for backend rollout
      kubernetes.core.k8s_info:
        api_version: apps/v1
        kind: Deployment
        name: "{{ release_name }}-backend"
        namespace: "{{ namespace }}"
        wait: true
        wait_condition:
          type: Available
          status: "True"
        wait_timeout: 120

    - name: Get backend service info
      kubernetes.core.k8s_info:
        api_version: v1
        kind: Service
        name: "{{ release_name }}-backend"
        namespace: "{{ namespace }}"
      register: backend_svc

    - name: Get aggregator service info
      kubernetes.core.k8s_info:
        api_version: v1
        kind: Service
        name: "{{ release_name }}-aggregator"
        namespace: "{{ namespace }}"
      register: aggregator_svc

    - name: Print deployment summary
      ansible.builtin.debug:
        msg:
          - "✓ CSI stack deployed to namespace '{{ namespace }}'"
          - "  Aggregator UDP: {{ aggregator_svc.resources[0].status.loadBalancer.ingress[0].ip | default('NodePort — check kubectl get svc') }}:5005"
          - "  Backend HTTP:   {{ backend_svc.resources[0].status.loadBalancer.ingress[0].ip | default('via Ingress') }}:8000"
          - ""
          - "  Flash ESP32 firmware with AGGREGATOR_HOST pointing at the aggregator IP above."
