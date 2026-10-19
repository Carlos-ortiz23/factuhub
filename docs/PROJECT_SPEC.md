> **Nota de vigencia (2026-10-19):** este documento se conserva verbatim tal
> como fue entregado. Su título y la línea `**Nombre provisional:** ConciliApp`
> quedaron superados por una corrección explícita del usuario: el producto es
> **FactuHub**. Por lo tanto, donde el texto original dice `ConciliApp` o
> `conciliapp/`, léase `FactuHub` y la raíz del monorepo `factuhub/`. El resto
> de la especificación sigue vigente sin cambios.

# ESPECIFICACIÓN TÉCNICA DEL PROYECTO

## Plataforma web de conciliación bancaria inteligente

**Nombre provisional:** ConciliApp
**Mercado inicial:** Colombia
**Usuarios objetivo:** Contadores internos de empresas
**Integración inicial:** World Office
**Modalidad:** Aplicación web SaaS, preparada para múltiples empresas
**Enfoque:** Lectura inicial de información contable, conciliación automatizada y escritura futura bajo aprobación humana.
**Estado:** Especificación para iniciar el desarrollo con OpenCode.

---

# 1. VISIÓN DEL PROYECTO

Desarrollar una plataforma web que ayude a los contadores a realizar conciliaciones bancarias de forma más rápida, precisa y trazable.

La plataforma debe comparar los movimientos de un extracto bancario con los movimientos contables de la empresa, identificar coincidencias, detectar diferencias y permitir que el contador revise, confirme o rechace las sugerencias generadas.

El objetivo no es reemplazar el software contable existente, sino complementarlo mediante una capa especializada de conciliación.

## 1.1. Problema que resuelve

Actualmente, muchos procesos de conciliación requieren:

- Descargar extractos bancarios.
- Exportar auxiliares contables.
- Comparar registros manualmente en Excel.
- Buscar movimientos faltantes o duplicados.
- Investigar diferencias entre fechas, importes y referencias.
- Preparar informes de cierre.
- Documentar las decisiones tomadas durante la conciliación.

La plataforma debe automatizar las tareas repetitivas y permitir que el contador concentre su trabajo en las diferencias que realmente necesitan análisis.

## 1.2. Objetivos principales

1. Reducir el tiempo dedicado a conciliaciones bancarias.
2. Identificar coincidencias entre movimientos bancarios y contables.
3. Detectar transacciones faltantes, duplicadas o inconsistentes.
4. Gestionar movimientos pendientes de conciliación.
5. Facilitar la revisión y aprobación por parte del contador.
6. Generar informes exportables.
7. Integrarse progresivamente con World Office.
8. Mantener un historial verificable de las operaciones realizadas.
9. Preparar una arquitectura extensible para integrar otros sistemas contables en el futuro.

## 1.3. Principios fundamentales

- No modificar silenciosamente los datos originales.
- No inventar coincidencias para forzar una conciliación.
- No aprobar automáticamente movimientos dudosos.
- No crear asientos contables sin autorización explícita.
- No depender exclusivamente de inteligencia artificial para validar importes o saldos.
- Mantener trazabilidad de todas las decisiones importantes.
- Separar los datos de cada empresa.
- Diseñar la plataforma para que sea útil incluso cuando una integración API no esté disponible.

---

# 2. ALCANCE DEL MVP

La primera versión debe permitir completar una conciliación bancaria de principio a fin para una empresa, una cuenta bancaria y un periodo contable.

## 2.1. Funcionalidades incluidas

### A. Autenticación y usuarios

- Registro e inicio de sesión.
- Recuperación de acceso.
- Gestión de usuarios de una empresa.
- Roles y permisos.
- Separación de información por empresa.
- Registro de acciones importantes.

### B. Gestión de empresas

- Crear y editar empresas.
- Registrar identificación tributaria.
- Asociar usuarios.
- Configurar cuentas bancarias.
- Configurar la integración contable.
- Consultar periodos de conciliación.

### C. Integración contable

- Configurar una conexión con World Office.
- Probar la conexión.
- Consultar los recursos contables que la API permita recuperar.
- Registrar el estado de la última sincronización.
- Informar errores de conexión.
- Permitir importación de archivos cuando no exista un recurso API adecuado.

### D. Importación de archivos

Aceptar inicialmente archivos CSV y XLSX.

Permitir importar:

- Extractos bancarios.
- Auxiliares contables.
- Exportaciones de movimientos.
- Saldos de apertura y cierre cuando estén disponibles.

El importador debe permitir mapear columnas si los archivos utilizan estructuras diferentes.

Debe validar fechas, importes, débitos, créditos, referencias y campos obligatorios.

### E. Motor de conciliación

- Coincidencia exacta.
- Coincidencia aproximada.
- Coincidencia por referencia.
- Comparación de fechas.
- Detección de posibles duplicados.
- Agrupación de varios movimientos contra uno o uno contra varios.
- Detección de movimientos sin contraparte.
- Explicación de las sugerencias.
- Prevención de asociaciones duplicadas.

### F. Revisión de resultados

- Confirmar coincidencias.
- Rechazar sugerencias.
- Deshacer asociaciones cuando esté permitido.
- Registrar observaciones.
- Filtrar movimientos pendientes.
- Consultar el historial.
- Enviar el periodo a revisión.
- Aprobar o reabrir una conciliación según los permisos.

### G. Informes

- Resumen de saldos.
- Movimientos conciliados.
- Movimientos pendientes.
- Diferencias identificadas.
- Partidas en tránsito.
- Comisiones y otros movimientos no registrados.
- Informe descargable en Excel.
- Registro de aprobación.

## 2.2. Funcionalidades que no deben desarrollarse inicialmente

- Sistema completo de contabilidad.
- Facturación electrónica.
- Nómina.
- Conciliación tributaria.
- Integraciones bancarias directas con todos los bancos.
- Escritura automática de asientos contables.
- Aprobación automática mediante IA.
- Arquitectura de microservicios.
- Aplicación móvil nativa.

La primera versión debe priorizar una conciliación confiable antes de ampliar el alcance.

---

# 3. STACK TECNOLÓGICO

Utilizar un stack moderno, mantenible y apropiado para un producto financiero.

## 3.1. Frontend

**Tecnologías:**

- Next.js.
- React.
- TypeScript.
- Tailwind CSS.
- shadcn/ui.
- React Hook Form.
- Zod para validación de formularios.
- TanStack Table para tablas de movimientos.
- Una biblioteca de gráficos únicamente cuando aporte valor al dashboard.

El frontend debe ser modular, accesible, adaptable a diferentes tamaños de pantalla y adecuado para trabajar con grandes tablas de movimientos.

## 3.2. Backend

**Tecnologías:**

- Python.
- FastAPI.
- Pydantic.
- SQLAlchemy 2.
- Alembic.
- HTTPX para solicitudes a servicios externos.
- openpyxl para archivos XLSX.
- Pandas cuando sea útil para procesamiento tabular.
- pytest para pruebas.

El backend será responsable de la autenticación, permisos, importaciones, normalización, conciliación, informes e integración contable.

## 3.3. Base de datos

PostgreSQL.

Utilizar:

- UUID como identificadores.
- Restricciones de integridad.
- Índices para consultas frecuentes.
- Transacciones SQL para confirmar conciliaciones.
- Migraciones con Alembic.
- Row-Level Security como protección adicional para datos de diferentes empresas.
- Importes almacenados de manera exacta, nunca utilizando números de punto flotante para operaciones financieras.

## 3.4. Procesamiento asíncrono

El MVP puede comenzar con tareas de procesamiento ejecutadas por el backend.

Si el volumen de archivos o las sincronizaciones lo requieren, incorporar:

- Redis.
- Celery.
- Trabajadores de procesamiento independientes.

Las importaciones extensas y las sincronizaciones no deben bloquear las solicitudes HTTP durante periodos prolongados.

## 3.5. Almacenamiento

Utilizar almacenamiento privado compatible con S3 para archivos originales, reportes y documentos temporales.

Los archivos financieros nunca deben estar disponibles públicamente.

## 3.6. Despliegue

Preparar:

- Docker para desarrollo y despliegue.
- Variables de entorno.
- Entornos independientes de desarrollo, pruebas y producción.
- Copias de seguridad.
- Registro centralizado de errores.
- Monitoreo básico.
- Migraciones controladas.

No implementar microservicios durante el MVP. Utilizar un backend modular con responsabilidades claramente separadas.

---

# 4. ARQUITECTURA GENERAL

La aplicación seguirá una arquitectura modular.

## 4.1. Componentes

### Frontend

Responsable de:

- Interfaz.
- Formularios.
- Tablas.
- Filtros.
- Visualización de resultados.
- Acciones de revisión y aprobación.
- Descarga de informes.

### API backend

Responsable de:

- Autenticación.
- Autorización.
- Validación de datos.
- Gestión de empresas.
- Gestión de conexiones.
- Importaciones.
- Conciliación.
- Auditoría.
- Generación de reportes.

### Capa de integración

Responsable de:

- Conectar con World Office.
- Centralizar autenticación externa.
- Consultar los recursos disponibles.
- Convertir respuestas externas a un modelo interno.
- Gestionar errores y límites de solicitudes.
- Sincronizar movimientos sin duplicarlos.

### Motor de conciliación

Responsable de:

- Normalizar datos.
- Encontrar candidatos.
- Calcular puntajes.
- Aplicar reglas de compatibilidad.
- Identificar coincidencias agrupadas.
- Evitar asociaciones conflictivas.
- Explicar las decisiones del algoritmo.

### PostgreSQL

Almacena usuarios, empresas, cuentas, movimientos, conciliaciones, conexiones y auditoría.

### Almacenamiento de archivos

Conserva los archivos originales y los reportes generados mediante permisos controlados.

## 4.2. Flujo principal

1. El usuario inicia sesión.
2. Selecciona una empresa.
3. Selecciona una cuenta bancaria.
4. Crea un periodo de conciliación.
5. Importa el extracto bancario.
6. Obtiene los movimientos contables desde World Office o importa un auxiliar.
7. El sistema valida y normaliza los datos.
8. El motor genera coincidencias sugeridas.
9. El contador revisa las partidas.
10. Confirma o rechaza las asociaciones.
11. Investiga las diferencias.
12. Genera el informe.
13. El responsable revisa y aprueba el periodo.

---

# 5. INTEGRACIÓN CON WORLD OFFICE

Esta integración debe construirse como un adaptador independiente.

## 5.1. Primera verificación obligatoria

Antes de desarrollar el conector, confirmar si la empresa piloto utiliza:

- World Office Cloud.
- World Office de escritorio.
- Otra modalidad o versión del producto.

No asumir que todas las instalaciones tienen la misma API.

Documentación oficial para investigar:

- https://developer.worldoffice.cloud/documentacion.html
- https://developer.worldoffice.cloud/guiaInterfaz.html
- https://api.worldoffice.cloud/swagger

La existencia de una API publicada no garantiza que permita recuperar todos los movimientos bancarios necesarios para conciliar.

## 5.2. Recursos que deben verificarse

Investigar en la documentación oficial los siguientes recursos publicados para World Office Cloud:

- `POST /api/v1/contabilidad/listarDocContable`
- `POST /api/v1/contabilidad/contabilizaciones`
- `POST /api/v1/contabilidad/asientos/{documentoId}`

Verificar parámetros, permisos, paginación, estructura de respuestas y disponibilidad de filtros por fecha y cuenta.

No asumir que estos recursos constituyen un endpoint de movimientos bancarios.

El objetivo es comprobar si permiten recuperar:

- Cuentas contables.
- Fechas.
- Débitos.
- Créditos.
- Referencias.
- Descripciones.
- Identificadores externos.
- Información de documentos contabilizados.
- Identificación de la empresa y la cuenta bancaria.

Si no existe un recurso apropiado, usar exportaciones autorizadas a CSV/XLSX como mecanismo inicial.

No acceder directamente a la base de datos interna de World Office ni realizar consultas no autorizadas.

## 5.3. Diseño del adaptador

Crear:

`backend/app/integrations/world_office/`

Con estos módulos:

- `client.py`: cliente HTTP.
- `auth.py`: gestión de autenticación.
- `schemas.py`: validación de respuestas externas.
- `mapper.py`: conversión al modelo interno.
- `capabilities.py`: operaciones soportadas.
- `service.py`: lógica de sincronización.
- `exceptions.py`: errores específicos.
- `tests/`: pruebas del adaptador.

Definir una interfaz común:

```python
from datetime import date
from typing import Protocol


class AccountingConnector(Protocol):

    async def test_connection(self) -> bool:
        ...

    async def list_bank_accounts(self) -> list[dict]:
        ...

    async def fetch_ledger_transactions(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        ...
```

Los métodos son contratos internos propuestos. Deben implementarse de acuerdo con las capacidades reales de la versión de World Office.

## 5.4. Autenticación

Centralizar las solicitudes HTTP en el cliente del conector.

La documentación de World Office Cloud describe autenticación mediante token y el uso del prefijo `WO` en la cabecera de autorización. Confirmar los detalles para la versión contratada antes de desplegar.

Reglas:

- Nunca exponer tokens en el navegador.
- Nunca guardar credenciales en el repositorio.
- Utilizar secretos cifrados.
- Evitar registrar cabeceras de autenticación.
- Implementar tiempos de espera.
- Gestionar errores HTTP.
- Limitar los reintentos.
- Registrar la última sincronización exitosa.
- Mantener un estado visible de conexión.

## 5.5. Modo de funcionamiento

Implementar dos mecanismos:

**Modo API:** obtiene movimientos contables mediante los recursos oficiales verificados.

**Modo archivo:** importa exportaciones de World Office cuando no exista un recurso adecuado.

Ambos deben producir los mismos modelos internos para que el motor de conciliación funcione independientemente de la fuente.

---

# 6. ESTRUCTURA DEL REPOSITORIO

Organizar el proyecto en un monorepo:

```text
conciliapp/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── dashboard/
│   │   │   ├── organizations/
│   │   │   ├── connections/
│   │   │   ├── imports/
│   │   │   ├── bank-accounts/
│   │   │   ├── reconciliation/
│   │   │   ├── reports/
│   │   │   └── audit/
│   │   ├── lib/
│   │   ├── hooks/
│   │   └── types/
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── imports/
│   │   ├── integrations/
│   │   │   └── world_office/
│   │   ├── reconciliation/
│   │   ├── reports/
│   │   └── audit/
│   ├── migrations/
│   ├── tests/
│   └── pyproject.toml
├── docs/
│   ├── architecture.md
│   ├── database.md
│   ├── world-office-integration.md
│   └── reconciliation-rules.md
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

Adaptar la estructura si el proyecto existente ya tiene convenciones establecidas. No duplicar módulos o configuraciones sin necesidad.

---

# 7. MODELO DE DATOS

Crear inicialmente las siguientes tablas:

1. `organizations`
2. `users`
3. `organization_members`
4. `accounting_connections`
5. `bank_accounts`
6. `import_jobs`
7. `reconciliation_periods`
8. `bank_transactions`
9. `ledger_transactions`
10. `reconciliation_period_transactions`
11. `reconciliation_matches`
12. `reconciliation_match_items`
13. `audit_logs`

## 7.1. Organizaciones

Campos:

- `id`
- `name`
- `tax_id`
- `created_at`

Cada empresa constituye un espacio de datos aislado.

## 7.2. Usuarios y permisos

`users`:

- `id`
- `email`
- `full_name`
- `created_at`

`organization_members`:

- `organization_id`
- `user_id`
- `role`

Roles iniciales:

- `admin`
- `accountant`
- `reviewer`
- `viewer`

La autorización debe verificarse en el backend para cada operación.

## 7.3. Conexiones contables

`accounting_connections`:

- `id`
- `organization_id`
- `provider`
- `connection_mode`
- `external_company_id`
- `secret_reference`
- `status`
- `last_sync_at`
- `created_at`

Estados:

- `pending`
- `active`
- `error`
- `revoked`

## 7.4. Cuentas bancarias

`bank_accounts`:

- `id`
- `organization_id`
- `connection_id`
- `account_name`
- `bank_name`
- `account_number_masked`
- `currency`
- `ledger_account_code`
- `external_account_id`
- `active`
- `created_at`

No almacenar números completos de cuentas bancarias cuando no sean necesarios.

## 7.5. Importaciones

`import_jobs`:

- `id`
- `organization_id`
- `bank_account_id`
- `source_type`
- `file_name`
- `file_sha256`
- `status`
- `rows_read`
- `rows_imported`
- `error_summary`
- `created_at`

Tipos de fuente:

- `bank_statement`
- `ledger_export`
- `api_sync`

Estados:

- `pending`
- `processing`
- `completed`
- `failed`

Las importaciones deben ser idempotentes y permitir identificar errores por fila.

## 7.6. Periodos de conciliación

`reconciliation_periods`:

- `id`
- `organization_id`
- `bank_account_id`
- `period_start`
- `period_end`
- `opening_balance_minor`
- `bank_closing_balance_minor`
- `ledger_closing_balance_minor`
- `status`
- `created_by`
- `approved_by`
- `approved_at`
- `created_at`

Estados:

- `open`
- `in_review`
- `approved`
- `reopened`

No permitir aprobar un periodo con diferencias no justificadas según las reglas definidas por la empresa.

## 7.7. Movimientos bancarios

`bank_transactions`:

- `id`
- `organization_id`
- `bank_account_id`
- `import_job_id`
- `transaction_date`
- `value_date`
- `amount_minor`
- `direction`
- `reference`
- `description`
- `external_id`
- `fingerprint`
- `created_at`

`direction`:

- `debit`
- `credit`

## 7.8. Movimientos contables

`ledger_transactions`:

- `id`
- `organization_id`
- `bank_account_id`
- `import_job_id`
- `source_system`
- `external_id`
- `transaction_date`
- `amount_minor`
- `direction`
- `reference`
- `description`
- `fingerprint`
- `created_at`

Los movimientos importados deben preservar su origen y sus datos originales relevantes.

## 7.9. Periodo y movimientos

Crear `reconciliation_period_transactions` para relacionar los movimientos con el periodo en el que se investigan.

La tabla debe registrar:

- `id`
- `organization_id`
- `period_id`
- `transaction_type`
- `transaction_id`
- `created_at`

`transaction_type` distingue los movimientos bancarios de los contables.

Implementar restricciones para evitar asociaciones inválidas entre empresas, cuentas y periodos.

## 7.10. Conciliaciones

`reconciliation_matches`:

- `id`
- `organization_id`
- `period_id`
- `match_type`
- `score`
- `status`
- `reviewed_by`
- `reviewed_at`
- `explanation`
- `created_at`

Tipos:

- `exact`
- `approximate`
- `grouped`
- `manual`

Estados:

- `suggested`
- `confirmed`
- `rejected`
- `cancelled`

`reconciliation_match_items`:

- `id`
- `match_id`
- `bank_transaction_id`, nullable
- `ledger_transaction_id`, nullable
- `created_at`

Cada fila debe asociar un movimiento bancario o un movimiento contable con una conciliación. Validar que no esté vacío ambos lados y que no se produzcan asociaciones duplicadas.

Las asociaciones agrupadas deben permitir que una conciliación incluya varios movimientos bancarios y varios movimientos contables.

La confirmación de una conciliación debe ejecutarse en una transacción SQL, con bloqueo de los registros relevantes para evitar que dos usuarios confirmen simultáneamente el mismo movimiento.

## 7.11. Auditoría

`audit_logs`:

- `id`
- `organization_id`
- `user_id`
- `action`
- `entity_type`
- `entity_id`
- `metadata`
- `created_at`

Registrar:

- Importaciones.
- Sincronizaciones.
- Confirmaciones.
- Rechazos.
- Reaperturas.
- Aprobaciones.
- Cambios en conexiones.
- Cambios de permisos.

El historial no debe modificarse silenciosamente.

---

# 8. REGLAS DEL MOTOR DE CONCILIACIÓN

## 8.1. Normalización

Crear `reconciliation/normalizer.py`.

Funciones:

- Normalizar fechas.
- Normalizar referencias.
- Normalizar descripciones.
- Convertir importes a representación exacta.
- Homogeneizar débitos y créditos.
- Preservar datos originales.
- Detectar importaciones repetidas.

No modificar el valor original para forzar una coincidencia.

## 8.2. Coincidencia exacta

Crear `reconciliation/matcher.py`.

Buscar candidatos que cumplan:

1. Importe idéntico.
2. Dirección económica compatible.
3. Fecha igual o dentro de una ventana configurable.
4. Referencia coincidente cuando esté disponible.
5. Movimiento no conciliado previamente.

Si hay múltiples candidatos equivalentes, no elegir arbitrariamente. Mostrar las alternativas para revisión.

## 8.3. Coincidencia aproximada

Calcular un puntaje con variables normalizadas entre cero y uno:

- Importe: peso inicial 0,40.
- Fecha: peso inicial 0,25.
- Referencia: peso inicial 0,25.
- Descripción: peso inicial 0,10.

Fórmula:

`score = 0.40 * amount_score + 0.25 * date_score + 0.25 * reference_score + 0.10 * description_score`

Estos pesos son configurables y deben calibrarse con datos reales.

Umbrales iniciales:

- 0,95–1,00: alta confianza, sujeto a validaciones.
- 0,80–0,9499: sugerencia para revisión.
- Menos de 0,80: mantener pendiente o mostrar bajo solicitud.

El puntaje nunca sustituye las reglas de compatibilidad financiera.

## 8.4. Agrupaciones

Crear `reconciliation/grouping.py`.

Permitir investigar:

- Un movimiento bancario contra varios registros contables.
- Varios movimientos bancarios contra un registro contable.

Validar:

- Suma exacta de importes.
- Direcciones compatibles.
- Fechas razonables.
- Referencias relacionadas cuando existan.
- Ausencia de movimientos ya conciliados.
- Ausencia de asociaciones contradictorias.

Limitar inicialmente el tamaño de los grupos para evitar un crecimiento combinatorio excesivo.

Las comisiones bancarias y diferencias justificadas deben mostrarse como partidas explicables, no convertirse en coincidencias forzadas.

## 8.5. Duplicados

No utilizar únicamente fecha, importe y descripción para identificar duplicados.

El sistema debe distinguir entre:

- Duplicación de una misma importación.
- Reimportación del mismo movimiento.
- Dos transacciones legítimas con valores similares.
- Posibles duplicados que necesitan investigación.

La detección de duplicados no debe eliminar automáticamente movimientos originales.

## 8.6. Saldos

Crear `reconciliation/balances.py`.

Calcular:

- Saldo inicial bancario.
- Débitos y créditos bancarios.
- Saldo final del extracto.
- Saldo contable del periodo.
- Movimientos conciliados.
- Partidas pendientes.
- Diferencias no explicadas.
- Saldo conciliado según la convención contable configurada.

El cálculo debe validarse con un contador antes de utilizarse en producción.

Una diferencia neta de cero no demuestra por sí sola que todas las transacciones estén correctamente conciliadas.

---

# 9. API PROPIA

Usar FastAPI y versionar todas las rutas bajo `/api/v1`.

## 9.1. Organizaciones

- `GET /api/v1/organizations`
- `POST /api/v1/organizations`
- `GET /api/v1/organizations/{org_id}`
- `PATCH /api/v1/organizations/{org_id}`

## 9.2. Integraciones

- `GET /api/v1/organizations/{org_id}/connections`
- `POST /api/v1/organizations/{org_id}/connections/world-office`
- `POST /api/v1/organizations/{org_id}/connections/world-office/test`
- `POST /api/v1/connections/{connection_id}/sync`
- `GET /api/v1/connections/{connection_id}/status`

La conexión debe probarse en el backend y devolver errores seguros, sin exponer credenciales.

## 9.3. Cuentas bancarias

- `GET /api/v1/organizations/{org_id}/bank-accounts`
- `POST /api/v1/organizations/{org_id}/bank-accounts`
- `GET /api/v1/bank-accounts/{account_id}`

## 9.4. Importaciones

- `POST /api/v1/organizations/{org_id}/imports`
- `GET /api/v1/imports/{import_id}`
- `GET /api/v1/imports/{import_id}/errors`
- `POST /api/v1/imports/{import_id}/retry`

## 9.5. Periodos

- `POST /api/v1/bank-accounts/{account_id}/periods`
- `GET /api/v1/periods/{period_id}`
- `GET /api/v1/periods/{period_id}/summary`
- `GET /api/v1/periods/{period_id}/transactions`
- `POST /api/v1/periods/{period_id}/match-suggestions`
- `POST /api/v1/periods/{period_id}/submit-review`
- `POST /api/v1/periods/{period_id}/approve`
- `POST /api/v1/periods/{period_id}/reopen`

## 9.6. Coincidencias

- `GET /api/v1/periods/{period_id}/matches`
- `POST /api/v1/matches/{match_id}/confirm`
- `POST /api/v1/matches/{match_id}/reject`
- `POST /api/v1/matches/{match_id}/cancel`

Las operaciones deben comprobar permisos, estado actual y disponibilidad de todos los movimientos.

## 9.7. Informes

- `GET /api/v1/periods/{period_id}/report`
- `GET /api/v1/periods/{period_id}/report.xlsx`

Los reportes deben generarse desde el backend, validar permisos y no exponer información de otras empresas.

## 9.8. Convenciones de la API

- Usar Pydantic para validar solicitudes y respuestas.
- Implementar paginación.
- Validar todos los identificadores contra la empresa autorizada.
- Utilizar códigos HTTP correctos.
- Devolver mensajes de error claros sin revelar secretos.
- Implementar idempotencia para operaciones que puedan repetirse.
- Documentar la API con OpenAPI.
- Evitar operaciones financieras destructivas.
- Registrar las decisiones importantes en auditoría.

---

# 10. INTERFAZ DE USUARIO

Diseñar una interfaz empresarial moderna, sobria y enfocada en la productividad.

## 10.1. Dirección visual

- Fondo claro.
- Verde oscuro como color principal.
- Verde suave para estados positivos.
- Ámbar para advertencias.
- Rojo reservado para errores y diferencias relevantes.
- Tipografía legible.
- Tablas densas pero fáciles de leer.
- Navegación lateral.
- Filtros rápidos.
- Estados claramente identificados.
- Diseño adaptable a escritorio y móvil.

Evitar interfaces recargadas, gráficos decorativos y exceso de tarjetas.

## 10.2. Navegación principal

- Dashboard.
- Empresas.
- Cuentas bancarias.
- Conciliaciones.
- Integraciones.
- Informes.
- Auditoría.
- Configuración.

## 10.3. Dashboard

Mostrar:

- Empresas autorizadas.
- Cuentas bancarias activas.
- Periodos abiertos.
- Periodos pendientes de aprobación.
- Movimientos pendientes.
- Últimas importaciones.
- Errores de sincronización.
- Acceso rápido a una nueva conciliación.

Los indicadores deben calcularse desde datos reales, no ser valores estáticos.

## 10.4. Integraciones

Permitir:

- Configurar World Office.
- Consultar estado.
- Probar conexión.
- Seleccionar empresa.
- Consultar última sincronización.
- Ver errores.
- Revocar una conexión.

No mostrar tokens completos ni credenciales.

## 10.5. Centro de conciliación

Esta será la pantalla principal.

Incluir:

- Selector de empresa.
- Selector de cuenta.
- Selector de periodo.
- Resumen de saldos.
- Barra de progreso basada en movimientos correctamente conciliados.
- Pestañas para todas las transacciones, sugerencias, conciliados, pendientes y diferencias.
- Filtros por fecha, importe, referencia y descripción.
- Comparación de movimientos bancarios y contables.
- Explicación de cada coincidencia.
- Acciones para confirmar o rechazar.
- Registro de observaciones.
- Historial de decisiones.

Las cifras del dashboard deben coincidir con las del informe descargable.

## 10.6. Informe final

Incluir:

- Empresa.
- Cuenta bancaria.
- Periodo.
- Saldo inicial.
- Saldo final bancario.
- Saldo final contable.
- Débitos y créditos.
- Movimientos conciliados.
- Partidas pendientes.
- Diferencias justificadas.
- Diferencias no explicadas.
- Responsable.
- Revisor.
- Fecha de aprobación.

---

# 11. SEGURIDAD Y PROTECCIÓN DE DATOS

La información financiera debe tratarse como información confidencial.

## 11.1. Autenticación

- Sesiones seguras.
- Cookies `HttpOnly`, `Secure` y política `SameSite` adecuada si se utilizan cookies.
- Protección contra CSRF cuando corresponda.
- Recuperación de acceso segura.
- MFA recomendado para administradores y aprobadores.
- Limitación de intentos de autenticación.

## 11.2. Autorización

Comprobar en el backend:

- Empresa a la que pertenece el usuario.
- Rol.
- Permisos de lectura.
- Permisos de importación.
- Permisos de conciliación.
- Permisos de aprobación.
- Permisos de configuración de integraciones.

Aplicar Row-Level Security como capa adicional, no como sustituto de la autorización de la aplicación.

## 11.3. Secretos

- Utilizar variables de entorno para configuración local.
- Utilizar un gestor de secretos en producción.
- Cifrar credenciales externas.
- No guardar tokens en código fuente.
- No registrar cabeceras de autenticación.
- No devolver secretos al frontend.
- Rotar credenciales cuando corresponda.

## 11.4. Archivos

- Validar tamaño y tipo de archivo.
- Validar contenido real, no solo extensión.
- Procesar los archivos en entornos controlados.
- Evitar ejecutar macros.
- Limitar recursos consumidos durante la importación.
- Guardar los archivos en almacenamiento privado.
- Utilizar enlaces de descarga temporales.
- Definir una política de retención.

## 11.5. Integridad

- Utilizar transacciones SQL.
- Prevenir dobles confirmaciones.
- Registrar todas las aprobaciones.
- Conservar el origen de los movimientos.
- Evitar borrados destructivos.
- Implementar restauración de copias de seguridad.
- Realizar pruebas de recuperación.

## 11.6. Cumplimiento

Antes de procesar datos reales, revisar las obligaciones colombianas aplicables sobre protección de datos personales, confidencialidad, contratos, tratamiento de información y retención documental.

---

# 12. PRUEBAS OBLIGATORIAS

Crear pruebas unitarias, de integración, de seguridad y de aceptación.

## 12.1. Importación

- Archivo válido.
- Archivo vacío.
- Columnas faltantes.
- Fechas inválidas.
- Importes inválidos.
- Débitos y créditos.
- Archivo duplicado.
- Filas repetidas legítimas.
- Archivo de gran tamaño.
- Error parcial de importación.

## 12.2. Conciliación

- Coincidencia exacta.
- Fecha diferente dentro de tolerancia.
- Referencia coincidente.
- Referencia ausente.
- Dos candidatos equivalentes.
- Importe diferente.
- Dirección incompatible.
- Movimiento ya conciliado.
- Grupo de varios movimientos.
- Comisiones bancarias.
- Diferencias no explicadas.

## 12.3. Integridad

- Dos usuarios intentan confirmar el mismo movimiento.
- Un usuario intenta acceder a otra empresa.
- Una importación se repite.
- Un periodo se aprueba dos veces.
- Se intenta reabrir un periodo sin permisos.
- Se intenta confirmar una asociación contradictoria.

## 12.4. Saldos

Validar con casos preparados por un contador:

- Saldo inicial más movimientos.
- Débitos y créditos.
- Saldo final.
- Partidas en tránsito.
- Diferencias justificadas.
- Diferencias no explicadas.
- Periodos reabiertos.

## 12.5. Integración

- Credenciales inválidas.
- Token expirado.
- Recurso no autorizado.
- Timeout.
- Error del proveedor.
- Respuesta incompleta.
- Paginación.
- Reintentos.
- Sincronización repetida.

Las pruebas deben utilizar datos ficticios o datos reales debidamente autorizados y protegidos.

---

# 13. PLAN DE DESARROLLO

Estimar inicialmente entre seis y ocho semanas para un desarrollador experimentado trabajando a tiempo completo, sujeto a la disponibilidad de la API y al alcance final de la integración.

## Fase 1. Descubrimiento

- Confirmar la versión de World Office.
- Obtener documentación y credenciales de prueba.
- Obtener extractos y auxiliares de ejemplo.
- Validar los campos necesarios.
- Acordar reglas de saldos con un contador.
- Definir criterios de aceptación.

## Fase 2. Fundamentos

- Crear repositorio.
- Configurar frontend y backend.
- Configurar PostgreSQL.
- Implementar migraciones.
- Crear autenticación.
- Crear empresas y usuarios.
- Implementar roles y permisos.
- Añadir auditoría.

## Fase 3. Importación

- Crear importador CSV.
- Crear importador XLSX.
- Implementar mapeo de columnas.
- Normalizar movimientos.
- Detectar duplicados de importación.
- Implementar reporte de errores.
- Guardar archivos originales de manera segura.

## Fase 4. Integración

- Verificar los recursos oficiales de World Office.
- Implementar el cliente HTTP.
- Implementar el adaptador.
- Mapear respuestas al modelo interno.
- Añadir sincronización y reintentos.
- Implementar estados y errores de conexión.

Si la API no proporciona movimientos bancarios adecuados, continuar con archivos exportados sin bloquear el resto del MVP.

## Fase 5. Motor de conciliación

- Implementar coincidencias exactas.
- Implementar coincidencias aproximadas.
- Implementar prevención de asociaciones duplicadas.
- Implementar agrupaciones pequeñas.
- Crear bandeja de pendientes.
- Calcular saldos.
- Añadir confirmación y rechazo.
- Registrar decisiones.

## Fase 6. Informes

- Crear resumen del periodo.
- Crear exportación Excel.
- Implementar revisión y aprobación.
- Añadir reapertura controlada.
- Validar consistencia entre interfaz e informe.

## Fase 7. Piloto

- Ejecutar pruebas integrales.
- Revisar la seguridad.
- Validar resultados con un contador.
- Medir el tiempo de conciliación.
- Corregir falsos positivos.
- Documentar limitaciones.
- Preparar el despliegue.

---

# 14. CRITERIOS DE ACEPTACIÓN DEL MVP

El MVP estará listo para un piloto cuando cumpla todas estas condiciones:

1. Un usuario autorizado puede crear una empresa.
2. Puede registrar una cuenta bancaria.
3. Puede importar un extracto bancario y un auxiliar contable.
4. Puede revisar y corregir errores de importación.
5. Puede ejecutar la conciliación.
6. El motor genera sugerencias explicables.
7. El usuario puede confirmar y rechazar coincidencias.
8. Un movimiento no puede confirmarse en dos asociaciones incompatibles.
9. Los saldos coinciden con los casos de prueba aprobados por un contador.
10. Los movimientos pendientes pueden consultarse.
11. Se puede exportar un informe Excel.
12. Se conserva la trazabilidad de las decisiones.
13. Los usuarios no pueden acceder a datos de otras empresas.
14. La aplicación funciona sin conexión a World Office mediante el modo de importación de archivos.
15. La integración contable no expone credenciales ni permite escrituras no autorizadas.
16. Se han probado las rutas críticas y los casos de error.

No declarar que el sistema está listo solo porque la interfaz funciona. La integridad financiera, las pruebas de concurrencia y el aislamiento de datos son requisitos de aceptación.

---

# 15. INDICADORES PARA VALIDAR EL PRODUCTO

Durante el piloto, medir:

- Tiempo promedio de conciliación antes y después.
- Porcentaje de sugerencias aceptadas.
- Porcentaje de sugerencias rechazadas.
- Cantidad de partidas pendientes.
- Cantidad de duplicados detectados.
- Errores de importación.
- Tiempo de sincronización.
- Diferencias detectadas por periodo.
- Tiempo necesario para preparar el informe.
- Satisfacción del contador.

No establecer porcentajes de automatización como promesas comerciales hasta disponer de resultados medidos.

---

# 16. ESCRITURA FUTURA EN WORLD OFFICE

La primera versión debe trabajar en modo de solo lectura respecto al software contable.

Cuando el MVP esté validado, evaluar la posibilidad de registrar conciliaciones o asientos desde la plataforma.

Esta fase deberá incorporar:

- Permisos explícitos de escritura.
- Aprobación humana.
- Previsualización de cambios.
- Registro de la operación solicitada.
- Idempotencia.
- Control de concurrencia.
- Reintentos seguros.
- Confirmación de resultado.
- Manejo de operaciones parcialmente completadas.
- Auditoría completa.

No implementar esta funcionalidad hasta verificar que la API oficial permite las operaciones requeridas y que la licencia contratada las autoriza.

---

# 17. INSTRUCCIONES PARA OPENCODE

Actúa como un ingeniero de software sénior especializado en aplicaciones SaaS financieras, Python, FastAPI, PostgreSQL, Next.js y sistemas de conciliación bancaria.

Desarrolla este proyecto siguiendo esta especificación como documento principal.

## Reglas de trabajo

1. Antes de escribir código, inspecciona el repositorio y determina si existe una aplicación previa.
2. No sobrescribas código existente sin comprenderlo.
3. Identifica las herramientas disponibles y utiliza las versiones estables compatibles.
4. Crea un plan de implementación por fases.
5. Implementa un MVP funcional, no una colección de pantallas estáticas.
6. Mantén la separación entre frontend, API, importadores, integraciones y motor de conciliación.
7. No inventes endpoints de World Office.
8. Si no puedes verificar un recurso oficial, documenta la incertidumbre y crea una interfaz de integración preparada para implementarlo posteriormente.
9. Utiliza datos ficticios únicamente para demostraciones y pruebas.
10. Nunca incluyas credenciales reales en el repositorio.
11. No simules una integración real cuando no exista una conexión verificada.
12. No utilices datos ficticios en reportes que se presenten como resultados reales.
13. No implementes escritura contable sin autorización y sin una capacidad oficial verificada.
14. Escribe pruebas para todas las reglas financieras.
15. Ejecuta las pruebas después de cada fase.
16. Corrige los errores antes de avanzar.
17. Documenta las decisiones técnicas importantes.
18. No marques una tarea como completada si no ha sido probada.

## Orden de ejecución solicitado

### Primer paso

Inspecciona el entorno y presenta:

- Estado actual del repositorio.
- Archivos existentes.
- Tecnologías detectadas.
- Dependencias disponibles.
- Riesgos técnicos.
- Plan de implementación priorizado.

No elimines archivos ni hagas cambios destructivos durante esta inspección.

### Segundo paso

Prepara los fundamentos del proyecto:

- Estructura de carpetas.
- Configuración del entorno.
- Docker.
- PostgreSQL.
- Migraciones.
- Variables de entorno.
- README.
- Configuración de pruebas.

### Tercer paso

Implementa autenticación, empresas, usuarios, permisos y auditoría.

### Cuarto paso

Implementa importación CSV/XLSX y validación de movimientos.

### Quinto paso

Implementa el modelo de conciliación, las reglas de coincidencia y las pruebas financieras.

### Sexto paso

Implementa la interfaz del dashboard y el centro de conciliación conectados a la API real del proyecto.

### Séptimo paso

Investiga e implementa el adaptador de World Office únicamente con capacidades oficiales verificadas. Mantén la importación de archivos como alternativa.

### Octavo paso

Implementa informes, aprobación de periodos, pruebas integrales y documentación de despliegue.

## Resultado esperado

Al terminar el MVP, debe existir una aplicación que pueda iniciarse localmente, permita crear una empresa, importar movimientos bancarios y contables, generar coincidencias, revisar diferencias y exportar una conciliación.

La integración con World Office debe quedar operativa si los recursos oficiales necesarios están disponibles. Si no lo están, el proyecto debe seguir siendo funcional con archivos importados y dejar documentado exactamente qué falta para completar la integración.

**Empieza inspeccionando el repositorio y presentando el plan de implementación. No intentes construir todas las fases en una sola operación sin verificar cada resultado.** El design lo dejamos de ultimo UI/UX la idea es inspirarnos en diseños crear nuestra propia identidad de marca tengo un logo. para que este proyecto sea original y no copia y menos que parezca hecho por ia los iconos que utilizaremos seran de lucide, tipografia de google fonts pero una que se adapte perfectamente al proyecto. por eso en esto nos enfocamos despues vamos paso a paso siempre hacer prueba pero primero conectaremos repositorio que no esta conectado y siempre guardar en emgram para no perder el contexto de por donde quedamos, clean code y seguir todas las reglas legales para no tener problema. Clean code principios solid etc para codigo. no fallar en nada.... repositorio https://github.com/Carlos-ortiz23/factuhub.git
