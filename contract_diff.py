"""Offline, conservative change triage for MCP tools/list snapshots."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

LEVELS = ('info', 'review', 'risk')
MISSING = object()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def same(a, b):
    if a is MISSING or b is MISSING:
        return a is b
    return canonical(a) == canonical(b)


def pointer(part):
    return str(part).replace('~', '~0').replace('/', '~1')


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Clave JSON repetida: ' + key)
        obj[key] = value
    return obj


def load_snapshot(path):
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('El archivo supera 2 MiB')
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Número no finito')))
    return catalog(data)


def catalog(data):
    if not isinstance(data, dict):
        raise ValueError('Se espera un objeto tools/list')
    if 'error' in data:
        raise ValueError('La captura contiene un error JSON-RPC')
    body = data.get('result', data)
    if not isinstance(body, dict) or 'nextCursor' in body:
        raise ValueError('Se requiere un catálogo completo sin nextCursor; une todas las páginas')
    tools = body.get('tools')
    if not isinstance(tools, list) or len(tools) > 500:
        raise ValueError('tools debe ser una lista de hasta 500 herramientas')
    result = {}
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError('Herramienta no válida')
        name = tool.get('name')
        if not isinstance(name, str) or not name or len(name) > 128 or name in result:
            raise ValueError('Nombre vacío, demasiado largo o duplicado')
        if not isinstance(tool.get('inputSchema'), dict):
            raise ValueError('Cada herramienta necesita inputSchema como objeto')
        if 'outputSchema' in tool and not isinstance(tool['outputSchema'], dict):
            raise ValueError('outputSchema debe ser un objeto')
        check_shape(tool['inputSchema'])
        result[name] = tool
    return result


def check_shape(schema, depth=0):
    if depth > 40:
        raise ValueError('Esquema demasiado profundo')
    if isinstance(schema, dict):
        if 'required' in schema:
            req = schema['required']
            if not isinstance(req, list) or any(not isinstance(x, str) for x in req) or len(set(req)) != len(req):
                raise ValueError('required debe contener nombres únicos')
        if 'enum' in schema and (not isinstance(schema['enum'], list) or not schema['enum']):
            raise ValueError('enum debe ser una lista no vacía')
        # Walk only schema positions, never literal default/example/const values.
        for key in ('properties', '$defs', 'definitions', 'patternProperties', 'dependentSchemas'):
            if key in schema:
                if not isinstance(schema[key], dict):
                    raise ValueError(key + ' debe ser un objeto')
                for child in schema[key].values():
                    check_shape(child, depth + 1)
        for key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else', 'contains', 'propertyNames'):
            if key in schema:
                check_shape(schema[key], depth + 1)
        for key in ('anyOf', 'allOf', 'oneOf', 'prefixItems'):
            if key in schema:
                if not isinstance(schema[key], list):
                    raise ValueError(key + ' debe ser lista')
                for child in schema[key]:
                    check_shape(child, depth + 1)
    elif not isinstance(schema, bool):
        raise ValueError('Esquema anidado debe ser objeto o booleano')


def diff(old, new):
    changes = []

    def emit(tool, path, level, reason):
        changes.append(dict(tool=tool, path=path, level=level, reason=reason))

    def walk(tool, a, b, path):
        if canonical(a) == canonical(b):
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                x, y = a.get(key, MISSING), b.get(key, MISSING)
                p = path + '/' + pointer(key)
                if key in ('description', 'title', 'examples', 'default', '$comment'):
                    if not same(x, y):
                        emit(tool, p, 'info', 'Metadatos del esquema modificados')
                elif key == 'required' and isinstance(x if x is not MISSING else [], list) and isinstance(y if y is not MISSING else [], list):
                    before, after = set([] if x is MISSING else x), set([] if y is MISSING else y)
                    if after - before:
                        emit(tool, p, 'risk', 'Se añaden campos obligatorios')
                    if before - after:
                        emit(tool, p, 'info', 'Se eliminan obligaciones de entrada')
                elif key == 'enum' and isinstance(x, list) and isinstance(y, list):
                    before, after = {canonical(v) for v in x}, {canonical(v) for v in y}
                    if before - after:
                        emit(tool, p, 'risk', 'Se eliminan valores permitidos')
                    if after - before:
                        emit(tool, p, 'info', 'Se añaden valores permitidos')
                elif key in ('properties', '$defs', 'definitions', 'patternProperties', 'dependentSchemas') and isinstance(x, dict) and isinstance(y, dict):
                    for prop in sorted(x.keys() | y.keys()):
                        q = p + '/' + pointer(prop)
                        if prop not in x or prop not in y:
                            emit(tool, q, 'review', 'Entrada de esquema añadida o eliminada; revisar consumidores y restricciones')
                        else:
                            walk(tool, x[prop], y[prop], q)
                elif key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else', 'contains', 'propertyNames') and x is not MISSING and y is not MISSING:
                    walk(tool, x, y, p)
                elif not same(x, y):
                    emit(tool, p, 'review', 'Restricción modificada; no se demuestra compatibilidad')
        else:
            emit(tool, path, 'review', 'Esquema modificado; revisar compatibilidad')

    for name in sorted(old.keys() | new.keys()):
        if name not in new:
            emit(name, '', 'risk', 'Herramienta eliminada: llamadas antiguas dejan de resolver')
        elif name not in old:
            emit(name, '', 'info', 'Herramienta añadida')
        else:
            walk(name, old[name]['inputSchema'], new[name]['inputSchema'], '/inputSchema')
            for key in sorted((old[name].keys() | new[name].keys()) - {'name', 'inputSchema'}):
                if not same(old[name].get(key, MISSING), new[name].get(key, MISSING)):
                    level = 'info' if key in ('description', 'title', 'icons') else 'review'
                    emit(name, '/' + pointer(key), level, 'Metadato o contrato de salida modificado')
    counts = Counter(c['level'] for c in changes)
    return {'summary': {level: counts[level] for level in LEVELS}, 'changes': changes,
            'notice': 'Análisis estático orientativo; no certifica compatibilidad ni ejecuta herramientas.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--json', dest='output', type=Path)
    parser.add_argument('--fail-on', choices=('risk', 'review', 'any', 'none'), default='risk')
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve() in (args.before.resolve(), args.after.resolve()):
            raise ValueError('El informe no puede sobrescribir una entrada')
        report = diff(load_snapshot(args.before), load_snapshot(args.after))
        encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.output:
            args.output.write_text(encoded, encoding='utf-8')
        print(encoded, end='')
        levels = {'risk': {'risk'}, 'review': {'risk', 'review'}, 'any': set(LEVELS), 'none': set()}
        return int(any(c['level'] in levels[args.fail_on] for c in report['changes']))
    except (ValueError, OSError, RecursionError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
