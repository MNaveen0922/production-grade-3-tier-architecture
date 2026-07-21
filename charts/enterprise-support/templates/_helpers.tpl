{{/*
Common labels applied to every resource this chart creates.
*/}}
{{- define "enterprise-support.labels" -}}
app.kubernetes.io/part-of: {{ .Values.projectName }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/*
Full image reference for a service map entry (name/image/tag).
*/}}
{{- define "enterprise-support.image" -}}
{{ .root.Values.image.registry }}/{{ .svc.image }}:{{ .svc.tag }}
{{- end -}}
