{{/*
Expand the name of the chart.
*/}}
{{- define "grimnir.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully-qualified app name.
Truncated to 63 chars because Kubernetes name fields have that limit.
*/}}
{{- define "grimnir.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart label.
*/}}
{{- define "grimnir.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "grimnir.labels" -}}
helm.sh/chart: {{ include "grimnir.chart" . }}
{{ include "grimnir.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (used in matchLabels — must be stable across upgrades).
The component name is injected by callers via .component.
*/}}
{{- define "grimnir.selectorLabels" -}}
app.kubernetes.io/name: {{ include "grimnir.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .component }}
app.kubernetes.io/component: {{ .component }}
{{- end }}
{{- end }}

{{/*
Resolve image tag: use the explicit tag if set, otherwise fall back to AppVersion.
*/}}
{{- define "grimnir.geri.image" -}}
{{- $tag := .Values.image.geri.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.geri.repository $tag }}
{{- end }}

{{- define "grimnir.freki.image" -}}
{{- $tag := .Values.image.freki.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.freki.repository $tag }}
{{- end }}

{{- define "grimnir.nornir.image" -}}
{{- $tag := .Values.image.nornir.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.nornir.repository $tag }}
{{- end }}

{{- define "grimnir.volva.image" -}}
{{- $tag := .Values.image.volva.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.volva.repository $tag }}
{{- end }}

{{/*
Name of the Secret holding DATABASE_URL.
*/}}
{{- define "grimnir.dbSecretName" -}}
{{- if .Values.database.existingSecret }}
{{- .Values.database.existingSecret }}
{{- else }}
{{- printf "%s-db" (include "grimnir.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding MODEL_UPLOAD_SHARED_SECRET.
*/}}
{{- define "grimnir.modelUploadSecretName" -}}
{{- if .Values.modelUploadAuth.existingSecret }}
{{- .Values.modelUploadAuth.existingSecret }}
{{- else }}
{{- printf "%s-model-upload" (include "grimnir.fullname" .) }}
{{- end }}
{{- end }}
