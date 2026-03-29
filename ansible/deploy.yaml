---
# ansible/deploy.yaml
# Deploys the CSI stack to a Kubernetes cluster via Helm.
#
# Prerequisites on the control node:
#   pip install ansible kubernetes
#   ansible-galaxy collection install kubernetes.core community.docker
#
# Usage:
#   ansible-playbook ansible/deploy.yaml \
#     -e db_url="postgresql+asyncpg://csi_user:changeme@humpy.home.arpa:5432/csi" \
#     -e registry="your-registry.example.com" \
#     -e aggregator_lb_ip="192.168.1.50"

- name: Deploy CSI Localization Stack
  hosts: localhost
  connection: local
  gather_facts: false

  vars:
    release_name: csi
    namespace: csi
    chart_path: "{{ playbook_dir }}/../helm/csi"
    registry: "your-registry.example.com"
    image_tag: "latest"
    aggregator_lb_ip: ""
    db_url: ""  # required — pass via -e

  tasks:

    - name: Validate required vars
      ansible.builtin.assert:
        that: db_url != ""
        fail_msg: "db_url is required. Pass with -e db_url=postgresql+asyncpg://..."

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
          path: "{{ playbook_dir }}/.."
          dockerfile: aggregator/Dockerfile
        name: "{{ registry }}/csi-aggregator"
        tag: "{{ image_tag }}"
        source: build
        push: true

    - name: Build backend image
      community.docker.docker_image:
        build:
          path: "{{ playbook_dir }}/.."
          dockerfile: backend/Dockerfile
        name: "{{ registry }}/csi-backend"
        tag: "{{ image_tag }}"
        source: build
        push: true

    - name: Deploy Helm chart
      kubernetes.core.helm:
        name: "{{ release_name }}"
        chart_ref: "{{ chart_path }}"
        release_namespace: "{{ namespace }}"
        create_namespace: true
        wait: true
        values:
          image:
            aggregator:
              repository: "{{ registry }}/csi-aggregator"
              tag: "{{ image_tag }}"
            backend:
              repository: "{{ registry }}/csi-backend"
              tag: "{{ image_tag }}"
          database:
            url: "{{ db_url }}"
          service:
            aggregatorType: "{{ 'LoadBalancer' if aggregator_lb_ip else 'NodePort' }}"
            aggregatorLoadBalancerIP: "{{ aggregator_lb_ip }}"

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

    - name: Show aggregator service
      kubernetes.core.k8s_info:
        api_version: v1
        kind: Service
        name: "{{ release_name }}-aggregator"
        namespace: "{{ namespace }}"
      register: agg_svc

    - name: Print aggregator endpoint
      ansible.builtin.debug:
        msg: >
          Aggregator UDP endpoint:
          {{ agg_svc.resources[0].status.loadBalancer.ingress[0].ip | default('pending') }}:{{ agg_svc.resources[0].spec.ports[0].port }}
          — set AGGREGATOR_HOST in config.h to point here
