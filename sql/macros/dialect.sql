{#- The few places DuckDB and Snowflake SQL differ. Everything else in controls/ and
    sql/ is written in the subset both engines accept. `dialect` is set by the runner. -#}

{% macro full_match(expr, pattern) -%}
{%- if dialect == 'snowflake' -%}regexp_like({{ expr }}, '{{ pattern }}')
{%- else -%}regexp_full_match({{ expr }}, '{{ pattern }}'){%- endif -%}
{%- endmacro %}

{% macro replace_all(expr, pattern, replacement) -%}
{%- if dialect == 'snowflake' -%}regexp_replace({{ expr }}, '{{ pattern }}', '{{ replacement }}')
{%- else -%}regexp_replace({{ expr }}, '{{ pattern }}', '{{ replacement }}', 'g'){%- endif -%}
{%- endmacro %}
