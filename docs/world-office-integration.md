# World Office integration — verified findings

This document records what was **verified** against the public World Office
Cloud contract on 2026-10-19, and what remains **unknown**. It exists so nobody
has to guess later, and so no endpoint is ever invented.

Sources:

- `https://developer.worldoffice.cloud/documentacion.html` (Swagger UI shell)
- `https://developer.worldoffice.cloud/guiaInterfaz.html` (usage guide)
- `https://api.worldoffice.cloud/swagger` (OpenAPI 3.0.1, 101 paths)

## Verified

### Endpoints exist

All three resources named in the specification are present in the published
OpenAPI document:

| Method | Path |
| --- | --- |
| POST | `/api/v1/contabilidad/listarDocContable` |
| POST | `/api/v1/contabilidad/contabilizaciones` |
| POST | `/api/v1/contabilidad/asientos/{documentoId}` |

Related, potentially useful: `POST /api/v1/cuentasContables/listarCuentaContable`,
`GET /api/v1/cuentasContables/consultaCodigo/{codigo}`, plus `editarDocContable`,
`crearDocContable`, `anularDocumento/{documentoId}` (write operations, out of
scope for the MVP).

### Request shape is generic

Every accounting listing endpoint accepts the same pagination envelope, not a
resource-specific body:

```json
{
  "pagina": 1,
  "registroInicial": 0,
  "registrosPorPagina": 50,
  "columnaOrdenar": "string",
  "orden": "ASC",
  "filtros": [
    {
      "atributo": "string",
      "valor": "string",
      "tipoFiltro": "ENTRE",
      "tipoDato": "FECHA",
      "valor2": "string",
      "operador": "AND"
    }
  ],
  "totalElementos": 0,
  "canal": "API"
}
```

`tipoFiltro` supports `IGUAL`, `CONTIENE`, `MENOR_QUE`, `MAYOR_QUE`,
`EMPIEZA_CON`, `MAYOR_O_IGUAL`, `MENOR_O_IGUAL`, `TERMINA_CON`, `ENTRE`,
`IS_NULL`, `LENGTH`, `DIFERENTE`, `IS_NOT_NULL`, `LENGTH_IGUAL`, `NO_EMPIEZA_CON`.
`tipoDato` supports `STRING`, `BOOLEAN`, `NUMERIC`, `FECHA`, `LONG`, `LISTA`,
`IN`, `NOT_IN`, `ENUM`, `ENTIDAD`, `ARRAY_INT`.

### Response shape is generic

```json
{
  "status": "string",
  "userMessage": "string",
  "developerMessage": {},
  "errorCode": "string",
  "moreInfo": "string",
  "data": { "content": [], "totalPages": 0, "totalElements": 0, "number": 0 }
}
```

Documented status codes across these endpoints: `200`, `400`, `403`, `404`,
`409`, `500`.

### Authentication

- A token is generated **manually from the World Office Cloud application** by an
  API user, then sent on every request as `Authorization: WO <token>`.
- Without that header the API answers `401 Unauthorized`.
- API users have **per-service permissions** configured by an administrator, so a
  working token does not imply access to every resource.
- There is **no public login/token endpoint** in the OpenAPI document. Token
  provisioning is an operational step with the pilot company, not something the
  platform can automate.

## Unknown — must be resolved against a real tenant

These determine whether the API mode can fully replace file imports, and none of
them can be answered from published documentation:

1. The **attribute names** accepted by `filtros` for `listarDocContable` and
   `contabilizaciones` — in particular whether a date range (`ENTRE` + `FECHA`)
   and a ledger account code can be used as filters.
2. Whether any listing endpoint exposes **bank movements** with debit/credit
   amounts, references and descriptions, or only accounting documents whose
   ledger lines must be derived from `asientos/{documentoId}`.
3. The pagination limits actually enforced by the service (`registrosPorPagina`).
4. Whether the pilot company runs **World Office Cloud** or a desktop edition; a
   desktop installation may expose no API at all.

## Design consequences

- The connector is an **adapter with declared capabilities**
  (`integrations/world_office/capabilities.py`). The rest of the application never
  assumes a capability exists.
- Both modes (API and file) must produce the **same internal models**, so the
  reconciliation engine is source-agnostic.
- Until the unknowns above are resolved with real credentials, the **file import
  path is the primary one** and the integration must not be presented as working.
- Tokens stay server-side only: never in the browser, never logged, never in the
  repository, always over an encrypted secret reference.
