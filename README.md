# MCP Tool Contract Diff 🔌🔍

Detecta cambios en los catálogos de herramientas que podrían afectar a tus agentes antes de actualizar un servidor MCP. Compara dos capturas locales de `tools/list`, genera un informe JSON y devuelve un código de salida utilizable en CI.

Creado el **28 de octubre de 2026**. Código y ejemplos originales. **Python 3.10+; sin paquetes externos, APIs ni claves.**

## Instalación y ejemplo

```bash
git clone https://github.com/alvaroalcalaa/mcp-tool-contract-diff.git
cd mcp-tool-contract-diff
python contract_diff.py examples/before.json examples/after.json --json report.json
```

La demo representa una biblioteca ficticia de notas de diseño de videojuegos. En la nueva versión se exige `project`, desaparece un valor de `category`, se modifica la descripción y se añade una herramienta. Resultado esperado:

```json
{"info": 2, "review": 1, "risk": 2}
```

El comando termina con **1**, intencionadamente, porque encuentra riesgos. Una entrada del informe indica `tool: search_notes`, `path: /inputSchema/required`, `level: risk`. Las rutas usan JSON Pointer (escapan `/` y `~`). El informe completo también se imprime en la salida estándar.

```bash
# Revisar riesgos y cambios cuya compatibilidad no se demuestra
python contract_diff.py examples/before.json examples/after.json --fail-on review
# Solo generar el informe, sin fallar por cambios
python contract_diff.py examples/before.json examples/after.json --fail-on none
# Ejecutar las pruebas
python -m unittest -v
```

## Usarlo en tu proyecto

Exporta el resultado completo de `tools/list` de las dos versiones mediante tu cliente MCP habitual. Se admite tanto `{"tools": [...]}` como una respuesta JSON-RPC con `result.tools`. No se capturan catálogos desde esta utilidad. Si hay paginación, reúne todas las páginas en un único objeto `{"tools": [...]}`; cualquier `nextCursor` provoca un error para evitar interpretar una página incompleta como herramientas eliminadas.

Las herramientas deben tener nombres únicos y `inputSchema` como objeto. El orden de las herramientas, las claves de objetos y las listas `required` y `enum` no afecta al resultado. Se rechazan claves JSON duplicadas, nombres repetidos, números no finitos y algunos errores de forma habituales. Límite de 2 MiB por archivo, 500 herramientas y 40 niveles en las posiciones de esquema de entrada recorridas.

## Cómo interpretar los niveles

| Nivel | Cambios detectados | Acción sugerida |
|---|---|---|
| `risk` | Herramienta eliminada, nuevos campos obligatorios, valores de enum eliminados | Revisar llamadas antiguas y sus pruebas |
| `review` | Tipos y restricciones modificados, propiedades añadidas/eliminadas, cambios de outputSchema, annotations o campos desconocidos | Evaluación manual; puede ser compatible o incompatible |
| `info` | Herramienta nueva, obligaciones eliminadas, enum ampliado y metadatos descriptivos | Revisar impacto funcional si procede |

Se recorren esquemas de propiedades, elementos de arrays y otras posiciones comunes. Los cambios en composiciones como `oneOf`, referencias y palabras clave no interpretadas se señalan como revisión; no se resuelven referencias ni se descargan recursos. Una propiedad nueva requiere revisión porque podría restringir valores que antes se aceptaban como propiedades adicionales. Los cambios de salida siempre requieren revisión: su dirección de compatibilidad difiere de la entrada.

Códigos de salida: **0** sin cambios que activen el umbral; **1** umbral alcanzado; **2** entrada, argumentos o escritura incorrectos. `--fail-on` admite `risk` (predeterminado), `review` (incluye risk), `any` o `none`. El informe no puede sobrescribir las entradas.

## Límites reales

Es una herramienta de **triaje estático**, no un validador completo de JSON Schema ni una prueba de equivalencia. Un riesgo es una señal heurística, no la demostración de que existe una llamada válida que se romperá: las restricciones pueden interactuar. Un informe vacío significa que no se detectaron cambios estructurales relevantes; el comportamiento de un servidor puede variar aunque su catálogo sea idéntico. Los metadatos descriptivos también pueden influir en cómo un modelo elige herramientas.

No ejecuta herramientas, no mide respuestas de modelos y no verifica autenticación ni transporte MCP. Las pruebas usan capturas sintéticas originales y procesos CLI locales; **no se ha probado una integración con un servidor o cliente externo**. El informe omite valores de esquemas y descripciones, pero conserva nombres de herramientas y rutas de parámetros; revísalos antes de compartirlo. El archivo indicado por `--json` se reemplaza si existe y no es una entrada.

Referencia de formato consultada: [especificación oficial MCP, Tools (2025-11-25)](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/tools.mdx). Se usan `name`, `inputSchema` y `outputSchema`; no se pretende validar toda esa versión del protocolo.

## Licencia

MIT; consulta `LICENSE`.
