# Dashboard de Escenarios de Subsidios — Combustibles RD 2026

Panel de análisis de riesgo fiscal para el seguimiento del precio internacional del petróleo WTI y su impacto en el presupuesto de subsidios a los combustibles de la República Dominicana.

**🔗 Ver dashboard en vivo:** [jsanchezerazo.github.io/combustibles-rd-2026](https://jsanchezerazo.github.io/combustibles-rd-2026/)

---

## ¿Qué hace este dashboard?

- Monitorea el precio WTI en tiempo real y calcula el subsidio semanal estimado según la fórmula oficial
- Proyecta la ejecución presupuestal bajo tres escenarios: **Alivio** (WTI ≤$80), **Base** ($81–$110) y **Escalada** (>$110)
- Estima la semana de quiebre del presupuesto de RD$13,748M
- Identifica la zona de sostenibilidad fiscal y el umbral crítico de WTI para República Dominicana
- Se actualiza automáticamente todos los días a las **8:00 AM (hora RD)**

---

## Actualización automática

El dashboard se actualiza diariamente mediante **GitHub Actions** sin necesidad de intervención manual:

- **Fuente de datos:** Yahoo Finance (primaria) / EIA API (fallback)
- **Hora de ejecución:** 8:00 AM hora dominicana (12:00 UTC)
- **Script:** `update_dashboard.py` — obtiene el precio WTI, calcula el subsidio y actualiza `index.html`

---

## Archivos del repositorio

| Archivo | Descripción |
|---|---|
| `index.html` | Dashboard completo (HTML/CSS/JS, archivo único) |
| `update_dashboard.py` | Script de actualización automática diaria |
| `.github/workflows/update_dashboard.yml` | Configuración de GitHub Actions |

---

## Elaborado por

**Jorge Sánchez Erazo** — Consultor en comunicación política y análisis de riesgo
𝕏 [@jsanchezerazo](https://x.com/jsanchezerazo)
