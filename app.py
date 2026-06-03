import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import math
import io
import json
import requests

DEFAULT_AHORRO_RATIO = 0.3
RATIO_GASTOS_ALTO = 0.7
RATIO_AHORRO_BAJO = 0.1
RATIO_AHORRO_OBJETIVO = 0.2
OBJ_POR_FILA = 3

CATEGORIAS = ["Fondo de Emergencia", "Educación", "Vivienda", "Vehículo",
              "Viaje/Ocio", "Tecnología", "Salud", "Otro"]
PRIORIDADES = ["Baja", "Media", "Alta"]
PRIO_ORDER = {"Alta": 0, "Media": 1, "Baja": 2}
COLOR_PRIORIDAD = {"Alta": "#E74C3C", "Media": "#F1C40F", "Baja": "#3498DB"}
MONEDAS = ["ARS", "USD", "EUR"]

# ── PERFIL AVANZADO ────────────────────────────────────────────────────────────
# Pesos del scoring (deben sumar 1.0)
PESO_TOLERANCIA    = 0.35
PESO_CAPACIDAD     = 0.25
PESO_HORIZONTE     = 0.20
PESO_CONOCIMIENTO  = 0.10
PESO_OBJETIVO      = 0.10

OBJETIVOS_FINANCIEROS = [
    "Preservar capital",
    "Generar ingresos pasivos",
    "Compra de vivienda",
    "Jubilación / retiro",
    "Crecimiento patrimonial",
    "Independencia financiera",
    "Viaje / consumo a corto plazo",
]

# Mapa objetivo → ajuste de score (puede restringir recomendaciones)
OBJETIVO_SCORE_AJUSTE = {
    "Preservar capital":          -15,
    "Generar ingresos pasivos":    -5,
    "Compra de vivienda":          -5,
    "Jubilación / retiro":         +5,
    "Crecimiento patrimonial":     +5,
    "Independencia financiera":    +5,
    "Viaje / consumo a corto plazo": -20,
}

# Mapa objetivo → fuerza el plazo máximo permitido para renta variable
OBJETIVO_HORIZONTE_MINIMO = {
    "Compra de vivienda":          None,   # depende del plazo declarado
    "Viaje / consumo a corto plazo": 6,    # máximo 6 meses tolerable
}

# ── MEJORA 3: Mapa Categoría de meta → Objetivo financiero específico ──────────
# Permite que cada meta use su propio objetivo en el motor de recomendación,
# en lugar del objetivo general del perfil.
CATEGORIA_A_OBJETIVO = {
    "Fondo de Emergencia":  "Preservar capital",
    "Educación":            "Crecimiento patrimonial",
    "Vivienda":             "Compra de vivienda",
    "Vehículo":             "Preservar capital",
    "Viaje/Ocio":           "Viaje / consumo a corto plazo",
    "Tecnología":           "Preservar capital",
    "Salud":                "Preservar capital",
    "Otro":                 "Crecimiento patrimonial",
}

# ── TOOLTIPS de instrumentos financieros ───────────────────────────────────────
TOOLTIPS_INSTRUMENTOS = {
    "FCI money market": (
        "Fondo Común de Inversión que invierte en activos de muy corto plazo "
        "(Letras, cauciones). Permite rescatar el dinero en 24-48hs. "
        "Es el equivalente a una caja de ahorro con rendimiento."
    ),
    "FCI renta fija": (
        "Fondo que invierte en bonos y títulos de deuda. "
        "Ofrece rendimiento predecible con baja volatilidad. "
        "Ideal para plazos de 6 a 24 meses."
    ),
    "Bono CER": (
        "Bono del Tesoro argentino ajustado por CER (índice que sigue la inflación). "
        "Protege el capital de la inflación. Similar a los bonos UVA pero emitidos por el Estado."
    ),
    "Plazo fijo UVA": (
        "Depósito a plazo cuyo capital se ajusta por UVA (Unidad de Valor Adquisitivo), "
        "que sigue la inflación. Garantiza rendimiento real positivo con plazo mínimo de 90 días."
    ),
    "CEDEAR": (
        "Certificado de Depósito Argentino que representa acciones extranjeras (Apple, Google, etc.) "
        "cotizando en pesos en la Bolsa argentina. Permite invertir en empresas globales "
        "con cobertura implícita al dólar."
    ),
    "ETF": (
        "Exchange Traded Fund: fondo que cotiza en bolsa y replica un índice (ej: S&P 500). "
        "Permite diversificación instantánea con bajos costos. "
        "Ideal para inversores con conocimiento moderado que no quieren seleccionar acciones individuales."
    ),
    "Cartera Mixta 60/40": (
        "Estrategia clásica: 60% renta fija (bonos, FCI) + 40% renta variable (acciones, ETFs). "
        "Busca equilibrio entre protección y crecimiento. "
        "El 60/40 es el portafolio de referencia de la industria desde hace décadas."
    ),
    "Renta Variable": (
        "Inversión en acciones o instrumentos cuyo rendimiento no está garantizado. "
        "Mayor potencial de ganancia a largo plazo, pero con volatilidad significativa en el corto plazo. "
        "Requiere horizonte de al menos 3-5 años para mitigar el riesgo."
    ),
    "Cuenta remunerada": (
        "Cuenta bancaria o fintech que paga intereses diarios sobre el saldo disponible. "
        "Sin plazo mínimo, liquidez inmediata. "
        "Ejemplos en Argentina: Mercado Pago, Ualá, Naranja X."
    ),
}
# ───────────────────────────────────────────────────────────────────────────────

# Defaults editables por el usuario. Inflación y rendimiento son nominales anuales en %.
SUPUESTOS_DEFAULT = {
    "ARS": {"inflacion": 80.0, "rendimiento": 90.0},
    "USD": {"inflacion": 3.0, "rendimiento": 5.0},
    "EUR": {"inflacion": 2.5, "rendimiento": 4.0},
}
# ARS por 1 unidad de la moneda. ARS siempre 1.0 (pivote).
TIPOS_CAMBIO_DEFAULT = {"ARS": 1.0, "USD": 1200.0, "EUR": 1300.0}
CASAS_DOLAR = ["oficial", "blue", "bolsa", "contadoconliqui", "cripto", "tarjeta"]

PLAZO_CORTO_MAX = 3
PLAZO_MEDIO_MAX = 12
PLAZO_LARGO_MAX = 36

# RECOMENDACIONES legacy — mantenido para compatibilidad; la lógica principal
# ahora pasa por recomendar_instrumento_avanzado().
RECOMENDACIONES = {
    "corto": {
        "*": {"tipo": "Liquidez / Money Market",
              "descripcion": "FCI money market o cuenta remunerada. Rescate en 24-48hs, capital preservado.",
              "emoji": "🟢"},
    },
    "medio": {
        "Bajo": {"tipo": "Renta Fija",
                 "descripcion": "FCI de renta fija o bonos cortos. Rendimiento moderado, baja volatilidad.",
                 "emoji": "🟡"},
        "*": {"tipo": "Renta Fija con cobertura inflacionaria",
              "descripcion": "FCI renta fija + instrumento indexado UVA/CER. Protege el poder adquisitivo.",
              "emoji": "🟡"},
    },
    "largo": {
        "Bajo": {"tipo": "Renta Fija Diversificada",
                 "descripcion": "Mix de bonos y FCI de renta fija a mayor plazo.",
                 "emoji": "🟠"},
        "Medio": {"tipo": "Cartera Mixta 60/40",
                  "descripcion": "60% renta fija + 40% renta variable. Equilibrio entre estabilidad y crecimiento.",
                  "emoji": "🟠"},
        "Alto": {"tipo": "Renta Variable",
                 "descripcion": "Acciones locales o CEDEARs. Mayor volatilidad pero potencial de rendimiento real.",
                 "emoji": "🔴"},
    },
    "muy_largo": {
        "Bajo": {"tipo": "Renta Fija largo plazo",
                 "descripcion": "Bonos soberanos o FCI de duration alta.",
                 "emoji": "🟠"},
        "*": {"tipo": "Renta Variable / Cartera de crecimiento",
              "descripcion": "Acciones, CEDEARs o ETFs. El horizonte largo reduce el riesgo.",
              "emoji": "🔴"},
    },
}


# ── MOTOR DE PERFILAMIENTO AVANZADO ────────────────────────────────────────────

def clasificar_perfil(score: float) -> tuple[str, str]:
    """Devuelve (label, emoji) según el Risk Score 0-100."""
    if score <= 20:
        return "Muy Conservador", "🔵"
    if score <= 40:
        return "Conservador", "🟢"
    if score <= 60:
        return "Moderado", "🟡"
    if score <= 80:
        return "Moderado Agresivo", "🟠"
    return "Agresivo", "🔴"


# ── CATÁLOGO DE INSTRUMENTOS ──────────────────────────────────────────────────
# Cada instrumento tiene:
#   nombre, clase, moneda, riesgo (Bajo/Medio/Alto), liquidez, descripcion_corta
# Los nombres son reales del mercado argentino a 2025-2026.
CATALOGO = {
    # ── LIQUIDEZ ──────────────────────────────────────────────────────────────
    "FCI Money Market": {
        "clase": "Liquidez", "moneda": "ARS", "riesgo": "Bajo",
        "liquidez": "24-48hs",
        "desc": "FCI de rescate inmediato. Invierte en cauciones y Letras. Ej: Mercado Pago, Ualá, Naranja X.",
    },
    "Cuenta Remunerada": {
        "clase": "Liquidez", "moneda": "ARS", "riesgo": "Bajo",
        "liquidez": "Inmediata",
        "desc": "Cuentas fintech que pagan interés diario sobre el saldo. Sin plazo mínimo.",
    },
    "Caución Bursátil": {
        "clase": "Liquidez", "moneda": "ARS", "riesgo": "Bajo",
        "liquidez": "1-7 días",
        "desc": "Préstamo de corto plazo garantizado en Bolsa. Tasa más alta que cuenta remunerada.",
    },
    # ── RENTA FIJA ARS ────────────────────────────────────────────────────────
    "LEDE (Letra del Tesoro)": {
        "clase": "Renta Fija ARS", "moneda": "ARS", "riesgo": "Bajo",
        "liquidez": "Al vencimiento",
        "desc": "Letra de descuento del Tesoro Nacional. Plazos de 1 a 6 meses. Tasa fija en pesos.",
    },
    "Plazo Fijo UVA": {
        "clase": "Renta Fija ARS", "moneda": "ARS", "riesgo": "Bajo",
        "liquidez": "90 días mínimo",
        "desc": "Rendimiento = inflación + spread. Protección real garantizada. Mín. 90 días.",
    },
    "Bono CER (TX26/TX28)": {
        "clase": "Renta Fija ARS", "moneda": "ARS", "riesgo": "Medio",
        "liquidez": "Mercado secundario",
        "desc": "Bonos del Tesoro ajustados por CER (inflación). TX26 vence 2026, TX28 vence 2028.",
    },
    "FCI Renta Fija ARS": {
        "clase": "Renta Fija ARS", "moneda": "ARS", "riesgo": "Bajo",
        "liquidez": "48-72hs",
        "desc": "Fondos que combinan Lecaps, bonos CER y corporativos. Diversificación automática.",
    },
    "Lecap / Bono Tasa Fija": {
        "clase": "Renta Fija ARS", "moneda": "ARS", "riesgo": "Medio",
        "liquidez": "Mercado secundario",
        "desc": "Letras capitalizables del Tesoro. Tasa fija nominal. Indicado si esperás baja de inflación.",
    },
    # ── RENTA FIJA USD ────────────────────────────────────────────────────────
    "Bono Soberano USD (AL30/GD30)": {
        "clase": "Renta Fija USD", "moneda": "USD", "riesgo": "Alto",
        "liquidez": "Mercado secundario",
        "desc": "AL30 (Ley Argentina) y GD30 (Ley NY). Alto rendimiento pero riesgo soberano. Para inversores con tolerancia alta.",
    },
    "Obligación Negociable (ON) USD": {
        "clase": "Renta Fija USD", "moneda": "USD", "riesgo": "Medio",
        "liquidez": "Mercado secundario",
        "desc": "Deuda corporativa en dólares de empresas argentinas (YPF, Pampa, Telecom). Mejor calidad crediticia que soberanos.",
    },
    "FCI Renta Fija USD": {
        "clase": "Renta Fija USD", "moneda": "USD", "riesgo": "Medio",
        "liquidez": "48-72hs",
        "desc": "Fondos en dólares que combinan ONs y bonos internacionales. Diversificación con ticket bajo.",
    },
    "Bono del Tesoro USA (T-Bill/T-Note)": {
        "clase": "Renta Fija USD", "moneda": "USD", "riesgo": "Bajo",
        "liquidez": "Mercado secundario",
        "desc": "Deuda del gobierno de EE.UU. Riesgo casi nulo en USD. Accesible vía ETF (SHV, BIL, IEF).",
    },
    # ── RENTA VARIABLE ────────────────────────────────────────────────────────
    "CEDEAR S&P 500 (SPY/IVV)": {
        "clase": "Renta Variable", "moneda": "USD", "riesgo": "Medio",
        "liquidez": "Mercado (T+2)",
        "desc": "CEDEARs que replican el índice S&P 500. Diversificación en 500 empresas top de EE.UU. con cobertura implícita al dólar CCL.",
    },
    "CEDEAR Nasdaq (QQQ)": {
        "clase": "Renta Variable", "moneda": "USD", "riesgo": "Alto",
        "liquidez": "Mercado (T+2)",
        "desc": "Exposición a las 100 mayores tecnológicas del Nasdaq. Mayor volatilidad, mayor potencial de crecimiento.",
    },
    "CEDEAR Acciones Individuales": {
        "clase": "Renta Variable", "moneda": "USD", "riesgo": "Alto",
        "liquidez": "Mercado (T+2)",
        "desc": "CEDEARs de empresas como Apple, Google, Amazon, MercadoLibre. Requiere selección y seguimiento activo.",
    },
    "Acciones Merval (Argentinas)": {
        "clase": "Renta Variable", "moneda": "ARS", "riesgo": "Alto",
        "liquidez": "Mercado (T+2)",
        "desc": "Acciones del panel líder argentino (YPF, Banco Galicia, Grupo Financiero Valores). Alta volatilidad local.",
    },
    "ETF Global (VT / ACWI)": {
        "clase": "Renta Variable", "moneda": "USD", "riesgo": "Medio",
        "liquidez": "Mercado (T+2)",
        "desc": "Exposición a mercados globales (desarrollados + emergentes). Máxima diversificación geográfica.",
    },
    "ETF Sectorial / Temático": {
        "clase": "Renta Variable", "moneda": "USD", "riesgo": "Alto",
        "liquidez": "Mercado (T+2)",
        "desc": "ETFs de sectores específicos: energía (XLE), salud (XLV), tecnología (XLK). Mayor concentración.",
    },
    # ── ALTERNATIVOS ─────────────────────────────────────────────────────────
    "MEP / Dólar Bolsa": {
        "clase": "Cobertura Cambiaria", "moneda": "USD", "riesgo": "Bajo",
        "liquidez": "T+1 (parking 24hs)",
        "desc": "Compra de dólares en el mercado bursátil. No es una inversión en sí, sino cobertura cambiaria para metas en USD.",
    },
    "Real Estate / REITs": {
        "clase": "Alternativos", "moneda": "USD", "riesgo": "Medio",
        "liquidez": "Baja (REITs: media)",
        "desc": "Exposición a bienes raíces. REITs vía ETF (VNQ) para ticket bajo y liquidez. Diversificación real.",
    },
    "Cripto (BTC/ETH — fracción)": {
        "clase": "Alternativos", "moneda": "USD", "riesgo": "Muy Alto",
        "liquidez": "Alta (24/7)",
        "desc": "Bitcoin y Ethereum como reserva de valor especulativa. Máximo 5% del portafolio. Solo para horizontes >5 años y perfil agresivo.",
    },
}

# ── COLORES POR CLASE ─────────────────────────────────────────────────────────
COLOR_CLASE = {
    "Liquidez":             "#3498DB",
    "Renta Fija ARS":       "#2ECC71",
    "Renta Fija USD":       "#1ABC9C",
    "Renta Variable":       "#E74C3C",
    "Cobertura Cambiaria":  "#9B59B6",
    "Alternativos":         "#E67E22",
}

# ── MOTOR DE RECOMENDACIÓN SOFISTICADO ────────────────────────────────────────
def recomendar_instrumento_avanzado(
    risk_score: float,
    plazo_meses: int,
    objetivo: str,
    conocimiento_score: float,
    moneda_meta: str = "ARS",
) -> dict:
    """
    Motor de recomendación sofisticado.
    Devuelve:
      - tipo: nombre de la estrategia
      - emoji: color de riesgo
      - descripcion: justificación narrativa
      - allocations: lista de {instrumento, pct, clase, riesgo, liquidez, desc}
      - advertencias: lista de strings con alertas contextuales
    """
    advertencias = []
    usa_etf = conocimiento_score < 30
    meta_en_usd = moneda_meta == "USD"

    # ── Advertencias contextuales ─────────────────────────────────────────────
    if risk_score > 60 and plazo_meses < 24:
        advertencias.append(
            "⚠️ Tu perfil es agresivo pero el plazo es corto. "
            "Se reduce la exposición a renta variable para proteger el capital."
        )
    if conocimiento_score < 30 and risk_score > 60:
        advertencias.append(
            "📚 Tu score de conocimiento financiero es bajo. "
            "Se priorizan ETFs e índices sobre acciones individuales para reducir el riesgo de selección."
        )
    if meta_en_usd and risk_score < 40:
        advertencias.append(
            "💵 Tu meta está en USD. Se priorizan instrumentos con cobertura cambiaria "
            "aunque tu perfil sea conservador."
        )
    if plazo_meses > 60 and risk_score < 40:
        advertencias.append(
            "⏳ Con un horizonte tan largo, un perfil conservador puede quedarse corto frente a la inflación. "
            "Considerá incorporar gradualmente algo de renta variable."
        )

    def _build(tipo, emoji, desc, allocs):
        instrumentos = []
        for nombre, pct in allocs:
            cat = CATALOGO.get(nombre, {})
            instrumentos.append({
                "nombre": nombre,
                "pct": pct,
                "clase": cat.get("clase", "—"),
                "riesgo": cat.get("riesgo", "—"),
                "liquidez": cat.get("liquidez", "—"),
                "desc": cat.get("desc", ""),
                "color": COLOR_CLASE.get(cat.get("clase", ""), "#888"),
            })
        return {
            "tipo": tipo,
            "emoji": emoji,
            "descripcion": desc,
            "allocations": instrumentos,
            "advertencias": advertencias,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # REGLAS DE PRECEDENCIA (orden estricto)
    # ══════════════════════════════════════════════════════════════════════════

    # ── R1: Plazo ≤ 6 meses → siempre liquidez pura ──────────────────────────
    if plazo_meses <= 6:
        if meta_en_usd:
            return _build(
                "Liquidez en USD", "🟢",
                "Plazo menor a 6 meses con objetivo en USD. Capital garantizado en moneda dura. "
                "MEP para dolarizar + FCI dólar para rendimiento mínimo.",
                [("MEP / Dólar Bolsa", 60), ("FCI Renta Fija USD", 40)],
            )
        return _build(
            "Liquidez Total", "🟢",
            "Con menos de 6 meses no hay margen para asumir volatilidad. "
            "FCI money market permite rescate en 24-48hs sin riesgo de capital.",
            [("FCI Money Market", 70), ("Caución Bursátil", 30)],
        )

    # ── R2: Viaje / consumo ≤ 12 meses ───────────────────────────────────────
    if objetivo == "Viaje / consumo a corto plazo" and plazo_meses <= 12:
        return _build(
            "Liquidez con Cobertura Inflacionaria", "🟢",
            "Objetivo de consumo próximo. Se prioriza preservar el valor real "
            "con mínimo riesgo de mercado.",
            [("FCI Money Market", 50), ("Plazo Fijo UVA", 30), ("LEDE (Letra del Tesoro)", 20)],
        )

    # ── R3: Compra de vivienda ≤ 18 meses ────────────────────────────────────
    if objetivo == "Compra de vivienda" and plazo_meses <= 18:
        if meta_en_usd:
            return _build(
                "Preservación de Capital en USD", "🟡",
                "Compra de vivienda próxima en dólares. Sin exposición a renta variable. "
                "ONs corporativas + FCI dólar para rendimiento con riesgo acotado.",
                [("MEP / Dólar Bolsa", 40), ("Obligación Negociable (ON) USD", 40), ("FCI Renta Fija USD", 20)],
            )
        return _build(
            "Renta Fija Indexada (CER/UVA)", "🟡",
            "Compra de vivienda próxima en pesos. Instrumentos indexados a inflación "
            "para que el ahorro no pierda poder adquisitivo hasta el momento de compra.",
            [("Plazo Fijo UVA", 40), ("Bono CER (TX26/TX28)", 40), ("FCI Money Market", 20)],
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PERFILES POR RISK SCORE
    # ══════════════════════════════════════════════════════════════════════════

    # ── Muy Conservador (0-20) ────────────────────────────────────────────────
    if risk_score <= 20:
        if meta_en_usd:
            return _build(
                "Cartera Defensiva USD", "🔵",
                "Perfil muy conservador con objetivo en USD. Máxima preservación de capital "
                "en moneda dura. Sin exposición a renta variable.",
                [("MEP / Dólar Bolsa", 30), ("Bono del Tesoro USA (T-Bill/T-Note)", 40), ("FCI Renta Fija USD", 30)],
            )
        return _build(
            "Cartera Defensiva ARS", "🔵",
            "Capital preservado como prioridad absoluta. Instrumentos de máxima calidad "
            "crediticia con cobertura inflacionaria total.",
            [("FCI Money Market", 30), ("Plazo Fijo UVA", 40), ("Bono CER (TX26/TX28)", 30)],
        )

    # ── Conservador (21-40) ───────────────────────────────────────────────────
    if risk_score <= 40:
        if plazo_meses <= 24:
            if meta_en_usd:
                return _build(
                    "Renta Fija USD Corto Plazo", "🟢",
                    "Perfil conservador, horizonte corto, objetivo en USD. "
                    "ONs de alta calidad + T-Bills para rendimiento con riesgo mínimo.",
                    [("Obligación Negociable (ON) USD", 50), ("Bono del Tesoro USA (T-Bill/T-Note)", 30), ("FCI Renta Fija USD", 20)],
                )
            return _build(
                "Renta Fija ARS con Cobertura Inflacionaria", "🟢",
                "Perfil conservador, plazo medio. Instrumentos indexados para proteger "
                "el poder adquisitivo sin asumir volatilidad de renta variable.",
                [("Bono CER (TX26/TX28)", 40), ("Plazo Fijo UVA", 30), ("FCI Renta Fija ARS", 20), ("FCI Money Market", 10)],
            )
        if meta_en_usd:
            return _build(
                "Cartera Conservadora con Sesgo USD", "🟢",
                "Horizonte más largo permite incorporar algo de renta variable global "
                "aunque el perfil sea conservador.",
                [("Obligación Negociable (ON) USD", 40), ("Bono del Tesoro USA (T-Bill/T-Note)", 30), ("CEDEAR S&P 500 (SPY/IVV)", 20), ("FCI Renta Fija USD", 10)],
            )
        return _build(
            "Cartera Conservadora 80/20", "🟢",
            "80% en renta fija diversificada para estabilidad + 20% de exposición moderada "
            "a renta variable para no quedar rezagado frente a la inflación en horizontes largos.",
            [("Bono CER (TX26/TX28)", 35), ("FCI Renta Fija ARS", 25), ("Plazo Fijo UVA", 20), ("CEDEAR S&P 500 (SPY/IVV)", 20)],
        )

    # ── Moderado (41-60) ──────────────────────────────────────────────────────
    if risk_score <= 60:
        if plazo_meses <= 12:
            return _build(
                "Renta Fija Diversificada (Horizonte Corto)", "🟡",
                "Perfil moderado pero horizonte corto: sin tiempo para recuperar caídas "
                "de renta variable. Diversificación dentro de renta fija.",
                [("FCI Renta Fija ARS", 40), ("Bono CER (TX26/TX28)", 35), ("LEDE (Letra del Tesoro)", 25)],
            )
        if meta_en_usd:
            rv = "ETF Global (VT / ACWI)" if usa_etf else "CEDEAR S&P 500 (SPY/IVV)"
            return _build(
                "Cartera Mixta USD 55/45", "🟡",
                "Objetivo en USD con perfil moderado. Equilibrio entre renta fija dolarizada "
                "y renta variable global para crecimiento real.",
                [("Obligación Negociable (ON) USD", 35), ("Bono del Tesoro USA (T-Bill/T-Note)", 20), (rv, 30), ("FCI Renta Fija USD", 15)],
            )
        rv = "ETF Global (VT / ACWI)" if usa_etf else "CEDEAR S&P 500 (SPY/IVV)"
        return _build(
            "Cartera Mixta Clásica 60/40", "🟡",
            "El portafolio 60/40 es el estándar de la industria para inversores moderados. "
            "Equilibrio probado entre estabilidad y crecimiento a lo largo de décadas.",
            [("Bono CER (TX26/TX28)", 30), ("FCI Renta Fija ARS", 30), (rv, 30), ("FCI Money Market", 10)],
        )

    # ── Moderado Agresivo (61-80) ─────────────────────────────────────────────
    if risk_score <= 80:
        if plazo_meses < 24:
            rv = "CEDEAR S&P 500 (SPY/IVV)" if usa_etf else "CEDEAR Acciones Individuales"
            return _build(
                "Cartera de Crecimiento Moderado (Horizonte Limitado)", "🟠",
                "Perfil agresivo moderado con horizonte corto. Se reduce renta variable "
                "para no quedar atrapado en una caída cercana al momento de rescate.",
                [("FCI Renta Fija ARS", 30), ("Obligación Negociable (ON) USD", 25), (rv, 30), ("FCI Money Market", 15)],
            )
        if meta_en_usd:
            rv = "ETF Global (VT / ACWI)" if usa_etf else "CEDEAR Nasdaq (QQQ)"
            return _build(
                "Cartera de Crecimiento USD 25/75", "🟠",
                "Objetivo en USD con perfil moderado-agresivo. Alta exposición a renta variable "
                "global con colchón de renta fija para volatilidad.",
                [("Bono del Tesoro USA (T-Bill/T-Note)", 15), ("Obligación Negociable (ON) USD", 10), (rv, 50), ("CEDEAR S&P 500 (SPY/IVV)", 25)],
            )
        rv_principal = "CEDEAR S&P 500 (SPY/IVV)" if usa_etf else "CEDEAR Acciones Individuales"
        rv_secundario = "ETF Global (VT / ACWI)" if usa_etf else "CEDEAR Nasdaq (QQQ)"
        return _build(
            "Cartera de Crecimiento 30/70", "🟠",
            "70% en renta variable para maximizar rendimiento real a largo plazo. "
            "30% en renta fija como colchón de liquidez y estabilización ante caídas.",
            [(rv_principal, 40), (rv_secundario, 30), ("Bono CER (TX26/TX28)", 20), ("FCI Money Market", 10)],
        )

    # ── Agresivo (81-100) ─────────────────────────────────────────────────────
    if plazo_meses < 36:
        rv = "ETF Sectorial / Temático" if usa_etf else "CEDEAR Acciones Individuales"
        return _build(
            "Renta Variable con Diversificación Táctica", "🔴",
            "Perfil agresivo con horizonte moderado. Alta concentración en renta variable "
            "con diversificación geográfica para mitigar riesgo idiosincrático.",
            [("CEDEAR S&P 500 (SPY/IVV)", 35), (rv, 30), ("Acciones Merval (Argentinas)", 15), ("Obligación Negociable (ON) USD", 20)],
        )
    rv1 = "ETF Global (VT / ACWI)" if usa_etf else "CEDEAR Acciones Individuales"
    rv2 = "CEDEAR Nasdaq (QQQ)" if not usa_etf else "ETF Sectorial / Temático"
    return _build(
        "Cartera de Alto Crecimiento", "🔴",
        "Horizonte largo + perfil agresivo: condiciones óptimas para maximizar rendimiento real. "
        "Diversificación global con exposición a mercados emergentes, tecnología y activos alternativos.",
        [(rv1, 35), (rv2, 25), ("Acciones Merval (Argentinas)", 15), ("Real Estate / REITs", 15), ("Cripto (BTC/ETH — fracción)", 10)],
    )
# ─────────────────────────────────────────────────────────────────────────────
    """
    Motor de recomendación basado en risk_score, plazo, objetivo y conocimiento.

    Reglas de negocio (en orden de precedencia):
      1. Plazo < 6 meses  → siempre liquidez, sin importar perfil.
      2. Objetivo de corto plazo forzado (viaje, etc.) + plazo ≤ 12m → liquidez.
      3. Compra de vivienda con plazo ≤ 18 meses → renta fija máximo.
      4. Conocimiento < 30 → evitar acciones individuales, priorizar ETFs/FCI.
      5. Score alto + horizonte largo → renta variable permitida.
    """
    # ── Regla 1: plazo urgente ──────────────────────────────────────────────
    if plazo_meses <= 6:
        return {
            "tipo": "Liquidez / Money Market",
            "alternativas": ["Cuenta remunerada", "FCI money market"],
            "descripcion": (
                "Con menos de 6 meses de plazo, la prioridad es la liquidez inmediata. "
                "FCI money market o cuenta remunerada: rescate en 24-48hs, sin riesgo de capital."
            ),
            "emoji": "🟢",
        }

    # ── Regla 2: objetivo de consumo a corto plazo ──────────────────────────
    if objetivo == "Viaje / consumo a corto plazo" and plazo_meses <= 12:
        return {
            "tipo": "Liquidez / Renta Fija Corta",
            "alternativas": ["FCI money market", "Plazo fijo UVA"],
            "descripcion": (
                "Objetivo de consumo próximo. Se prioriza capital garantizado. "
                "Plazo fijo UVA o FCI money market para preservar el valor real."
            ),
            "emoji": "🟢",
        }

    # ── Regla 3: compra de vivienda con horizonte ≤ 18 meses ───────────────
    if objetivo == "Compra de vivienda" and plazo_meses <= 18:
        return {
            "tipo": "Renta Fija / Instrumentos CER-UVA",
            "alternativas": ["Plazo fijo UVA", "Bono CER corto", "FCI renta fija"],
            "descripcion": (
                "Compra de vivienda próxima: no se puede asumir volatilidad. "
                "Instrumentos indexados a inflación (UVA/CER) protegen el poder adquisitivo "
                "sin exponer el capital a caídas de mercado."
            ),
            "emoji": "🟡",
        }

    # ── Clasificación por score + plazo ────────────────────────────────────
    usa_etf = conocimiento_score < 30  # baja literacy → ETFs/FCI sobre acciones

    if risk_score <= 20:
        return {
            "tipo": "Renta Fija / Bonos Cortos",
            "alternativas": ["FCI renta fija", "Plazo fijo UVA", "Letras del Tesoro"],
            "descripcion": (
                "Perfil muy conservador: capital preservado es la prioridad absoluta. "
                "Instrumentos de renta fija con baja duration y emisores de alta calidad."
            ),
            "emoji": "🔵",
        }

    if risk_score <= 40:
        if plazo_meses <= 24:
            return {
                "tipo": "Renta Fija con cobertura inflacionaria",
                "alternativas": ["Bono CER", "FCI renta fija", "Plazo fijo UVA"],
                "descripcion": (
                    "Perfil conservador con horizonte medio. "
                    "Instrumentos indexados a inflación para proteger el poder adquisitivo "
                    "sin asumir volatilidad de renta variable."
                ),
                "emoji": "🟢",
            }
        return {
            "tipo": "Cartera Conservadora 80/20",
            "alternativas": ["FCI renta fija (80%)", "FCI balanceado (20%)", "Bonos soberanos"],
            "descripcion": (
                "80% renta fija diversificada + 20% activos con leve exposición a renta variable. "
                "El horizonte permite absorber volatilidad menor."
            ),
            "emoji": "🟢",
        }

    if risk_score <= 60:
        if plazo_meses <= 12:
            return {
                "tipo": "Renta Fija Diversificada",
                "alternativas": ["FCI renta fija", "Bonos CER", "Letras ajustables"],
                "descripcion": (
                    "Perfil moderado pero horizonte corto: el tiempo no alcanza para "
                    "recuperar caídas de renta variable. Se recomienda renta fija diversificada."
                ),
                "emoji": "🟡",
            }
        instrumento = "ETFs diversificados globales" if usa_etf else "CEDEARs de índices"
        return {
            "tipo": "Cartera Mixta 60/40",
            "alternativas": ["FCI balanceado", instrumento, "Bonos soberanos en USD"],
            "descripcion": (
                "60% renta fija + 40% renta variable. Equilibrio clásico entre estabilidad "
                f"y crecimiento. {'Se priorizan ETFs de índices por bajo conocimiento declarado en acciones individuales.' if usa_etf else 'Con tu nivel de conocimiento podés incorporar CEDEARs selectivos.'}"
            ),
            "emoji": "🟡",
        }

    if risk_score <= 80:
        if plazo_meses < 24:
            return {
                "tipo": "Cartera Mixta 50/50 con sesgo dinámico",
                "alternativas": ["FCI balanceado", "ETFs globales", "Bonos USD"],
                "descripcion": (
                    "Perfil moderado-agresivo pero con horizonte limitado. "
                    "Se modera la exposición a renta variable para evitar cristalizar pérdidas "
                    "si el mercado cae cerca del momento de rescate."
                ),
                "emoji": "🟠",
            }
        instrumento = "ETFs de renta variable (S&P 500, MSCI)" if usa_etf else "Acciones / CEDEARs selectivos"
        return {
            "tipo": "Cartera de Crecimiento 30/70",
            "alternativas": [instrumento, "FCI renta variable", "Bonos HY en USD"],
            "descripcion": (
                "30% renta fija como colchón de liquidez + 70% renta variable. "
                f"{'ETFs diversificados reducen el riesgo idiosincrático sin requerir selección de empresas individuales.' if usa_etf else 'Tu nivel de conocimiento te permite construir una cartera de acciones/CEDEARs con criterio propio.'}"
            ),
            "emoji": "🟠",
        }

    # score > 80: Agresivo
    if plazo_meses < 36:
        instrumento = "ETFs temáticos / sectoriales" if usa_etf else "Acciones locales e internacionales"
        return {
            "tipo": "Renta Variable con diversificación táctica",
            "alternativas": [instrumento, "CEDEARs", "FCI renta variable"],
            "descripcion": (
                "Perfil agresivo con horizonte moderado. Alta exposición a renta variable "
                "con diversificación geográfica y sectorial para mitigar concentración."
            ),
            "emoji": "🔴",
        }
    instrumento_rv = "ETFs de mercados emergentes y desarrollados" if usa_etf else "Acciones + CEDEARs + ETFs globales"
    return {
        "tipo": "Renta Variable / Cartera de Alto Crecimiento",
        "alternativas": [instrumento_rv, "Criptomonedas (fracción)", "REITs / Real assets"],
        "descripcion": (
            "Horizonte largo + perfil agresivo: condiciones ideales para maximizar "
            "rendimiento real. La diversificación geográfica y por clase de activo "
            "es clave. El tiempo juega a favor: las caídas son oportunidades de compra."
        ),
        "emoji": "🔴",
    }
# ───────────────────────────────────────────────────────────────────────────────

EXPORT_COLUMNS = ["Meta", "Categoría", "Prioridad", "Moneda",
                  "Costo Total", "Costo Futuro Estimado", "Ya Ahorrado",
                  "Plazo (Meses)", "Cuota Ideal", "Monto Asignado",
                  "Estado", "Instrumento Sugerido"]


def _bucket_plazo(meses):
    if meses <= PLAZO_CORTO_MAX:
        return "corto"
    if meses <= PLAZO_MEDIO_MAX:
        return "medio"
    if meses <= PLAZO_LARGO_MAX:
        return "largo"
    return "muy_largo"


@st.cache_data
def recomendar_instrumento(plazo_meses, perfil, risk_score=50, objetivo="Crecimiento patrimonial", conocimiento_score=50, moneda_meta="ARS"):
    """Wrapper unificado. Usa el motor avanzado cuando hay risk_score disponible."""
    return recomendar_instrumento_avanzado(risk_score, plazo_meses, objetivo, conocimiento_score, moneda_meta)


def convertir(monto, de_moneda, a_moneda, tipos_cambio):
    if de_moneda == a_moneda or monto == 0:
        return monto
    return monto * tipos_cambio[de_moneda] / tipos_cambio[a_moneda]


def _tasa_mensual(tasa_anual_pct):
    return (1 + tasa_anual_pct / 100) ** (1 / 12) - 1


def calcular_cuota_meta(obj, supuestos):
    """Calcula costo futuro, faltante y cuota mensual EN LA MONEDA DE LA META.

    Modelo:
      - Costo futuro = Costo * (1+π)^n con π mensual
      - Capital ya ahorrado se capitaliza a rendimiento r
      - Cuota mensual = anualidad ordinaria; si r=0 cae a faltante/n
    """
    n = int(obj.get("Plazo (Meses)") or 0)
    moneda = obj.get("Moneda") or "ARS"
    sup = supuestos.get(moneda, SUPUESTOS_DEFAULT[moneda])
    pi_m = _tasa_mensual(sup["inflacion"])
    r_m = _tasa_mensual(sup["rendimiento"])

    costo_presente = float(obj.get("Costo Total") or 0)
    ahorrado_presente = float(obj.get("Ya Ahorrado") or 0)

    costo_futuro = costo_presente * (1 + pi_m) ** n
    ahorrado_futuro = ahorrado_presente * (1 + r_m) ** n
    faltante = max(0.0, costo_futuro - ahorrado_futuro)

    if n <= 0 or faltante == 0:
        cuota_ideal = 0.0
    elif r_m > 1e-9:
        cuota_ideal = faltante * r_m / ((1 + r_m) ** n - 1)
    else:
        cuota_ideal = faltante / n

    return {
        "moneda_meta": moneda,
        "costo_futuro": costo_futuro,
        "ahorrado_futuro": ahorrado_futuro,
        "faltante_futuro": faltante,
        "cuota_ideal": cuota_ideal,
        "r_mensual": r_m,
    }


def meses_para_acumular(faltante_futuro, cuota, r_mensual):
    """Plazo real para acumular `faltante_futuro` ahorrando `cuota` por mes a tasa r."""
    if cuota <= 0:
        return None
    if r_mensual <= 1e-9:
        return math.ceil(faltante_futuro / cuota)
    base = 1 + faltante_futuro * r_mensual / cuota
    if base <= 0:
        return None
    return math.ceil(math.log(base) / math.log(1 + r_mensual))


def fecha_estimada_llegada(meses_desde_hoy: int) -> str:
    """Devuelve 'mes YYYY' calculado desde hoy + meses_desde_hoy."""
    from datetime import date
    from dateutil.relativedelta import relativedelta
    try:
        llegada = date.today() + relativedelta(months=meses_desde_hoy)
        meses_es = ["ene", "feb", "mar", "abr", "may", "jun",
                    "jul", "ago", "sep", "oct", "nov", "dic"]
        return f"{meses_es[llegada.month - 1]} {llegada.year}"
    except Exception:
        return f"~{meses_desde_hoy} meses"


def estado_meta(cuota_asignada, cuota_ideal):
    if cuota_asignada >= cuota_ideal and cuota_ideal > 0:
        return "En curso"
    if cuota_asignada > 0:
        return "Parcial"
    return "En espera"


def fmt(monto, codigo):
    return f"{codigo} {monto:,.2f}"


# ── MEJORA 1: Proyección temporal de capital acumulado ────────────────────────
def proyectar_capital(
    ahorrado_presente: float,
    cuota_mensual: float,
    r_mensual: float,
    n_meses: int,
) -> list[float]:
    """
    Devuelve una lista de n_meses+1 valores representando el capital acumulado
    al inicio de cada mes (mes 0 = valor inicial).
    Fórmula: capital[t] = capital[t-1] * (1+r) + cuota
    """
    capital = [ahorrado_presente]
    for _ in range(n_meses):
        siguiente = capital[-1] * (1 + r_mensual) + cuota_mensual
        capital.append(siguiente)
    return capital


def grafico_proyeccion(obj_enriquecido: dict, supuestos: dict) -> go.Figure:
    """
    Construye el gráfico de proyección del capital acumulado para una meta,
    mostrando la línea de capital objetivo (costo futuro) como referencia.
    """
    n = int(obj_enriquecido.get("Plazo (Meses)", 12))
    moneda = obj_enriquecido["moneda_meta"]
    sup = supuestos.get(moneda, SUPUESTOS_DEFAULT[moneda])
    r_m = _tasa_mensual(sup["rendimiento"])
    pi_m = _tasa_mensual(sup["inflacion"])

    capital_ideal = proyectar_capital(
        float(obj_enriquecido.get("Ya Ahorrado", 0)),
        obj_enriquecido["cuota_ideal_meta"],
        r_m, n,
    )
    capital_real = proyectar_capital(
        float(obj_enriquecido.get("Ya Ahorrado", 0)),
        obj_enriquecido["cuota_asignada_meta"],
        r_m, n,
    )
    costo_futuro_mes = [
        float(obj_enriquecido.get("Costo Total", 0)) * (1 + pi_m) ** t
        for t in range(n + 1)
    ]
    meses = list(range(n + 1))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=meses, y=costo_futuro_mes, name="Costo objetivo (ajustado por inflación)",
        line=dict(color="#E74C3C", dash="dash", width=1.5),
        hovertemplate=f"{moneda} %{{y:,.0f}}<extra>Objetivo</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=meses, y=capital_ideal, name="Capital con cuota ideal",
        line=dict(color="#2ECC71", width=2),
        hovertemplate=f"{moneda} %{{y:,.0f}}<extra>Cuota ideal</extra>",
        fill="tozeroy", fillcolor="rgba(46,204,113,0.08)",
    ))
    if obj_enriquecido["cuota_asignada_meta"] < obj_enriquecido["cuota_ideal_meta"]:
        fig.add_trace(go.Scatter(
            x=meses, y=capital_real, name="Capital con cuota asignada",
            line=dict(color="#F39C12", width=2, dash="dot"),
            hovertemplate=f"{moneda} %{{y:,.0f}}<extra>Cuota asignada</extra>",
        ))
    fig.update_layout(
        height=220,
        margin=dict(t=8, b=8, l=8, r=8),
        legend=dict(orientation="h", y=-0.25, font=dict(size=11)),
        xaxis_title="Meses",
        yaxis_title=moneda,
        hovermode="x unified",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ── MEJORA 2: Diagnóstico de Salud Financiera ─────────────────────────────────
def calcular_indicadores_salud(
    sueldo: float,
    total_gastos: float,
    ahorro_dispuesto: float,
    fondo_emergencia_meses: float,   # meses cubiertos por el fondo
    deuda_mensual: float = 0.0,      # cuota total de deudas por mes
) -> list[dict]:
    """
    Calcula KPIs financieros clave y devuelve una lista de dicts con:
      nombre, valor_display, estado ('ok'|'warning'|'error'), descripcion
    """
    indicadores = []

    # 1. Ratio de ahorro
    ratio_ahorro = ahorro_dispuesto / sueldo if sueldo > 0 else 0
    if ratio_ahorro >= 0.20:
        estado_aho, icono_aho = "ok", "✅"
    elif ratio_ahorro >= 0.10:
        estado_aho, icono_aho = "warning", "⚠️"
    else:
        estado_aho, icono_aho = "error", "🚨"
    indicadores.append({
        "nombre": "Tasa de ahorro",
        "valor": f"{ratio_ahorro:.1%}",
        "estado": estado_aho,
        "icono": icono_aho,
        "descripcion": (
            "Porcentaje del ingreso neto destinado al ahorro/inversión. "
            "Referencia: ≥20% excelente · 10-20% aceptable · <10% crítico."
        ),
        "benchmark": "≥ 20%",
    })

    # 2. Cobertura del fondo de emergencia
    if fondo_emergencia_meses >= 6:
        estado_fe, icono_fe = "ok", "✅"
    elif fondo_emergencia_meses >= 3:
        estado_fe, icono_fe = "warning", "⚠️"
    else:
        estado_fe, icono_fe = "error", "🚨"
    indicadores.append({
        "nombre": "Fondo de emergencia",
        "valor": f"{fondo_emergencia_meses:.1f} meses",
        "estado": estado_fe,
        "icono": icono_fe,
        "descripcion": (
            "Meses de gastos cubiertos por el fondo de liquidez disponible. "
            "Antes de invertir, cualquier asesor recomendará tener al menos 3-6 meses cubiertos."
        ),
        "benchmark": "≥ 6 meses",
    })

    # 3. Ratio gastos/ingresos
    ratio_gastos = total_gastos / sueldo if sueldo > 0 else 0
    if ratio_gastos <= 0.50:
        estado_gf, icono_gf = "ok", "✅"
    elif ratio_gastos <= 0.70:
        estado_gf, icono_gf = "warning", "⚠️"
    else:
        estado_gf, icono_gf = "error", "🚨"
    indicadores.append({
        "nombre": "Gastos fijos / ingresos",
        "valor": f"{ratio_gastos:.1%}",
        "estado": estado_gf,
        "icono": icono_gf,
        "descripcion": (
            "Regla 50/30/20: máximo 50% en necesidades fijas, "
            "30% en gastos variables/ocio, 20% en ahorro. "
            "Si superás el 70%, hay poco margen ante imprevistos."
        ),
        "benchmark": "≤ 50%",
    })

    # 4. Ratio deuda/ingreso
    ratio_deuda = deuda_mensual / sueldo if sueldo > 0 else 0
    if ratio_deuda <= 0.15:
        estado_deu, icono_deu = "ok", "✅"
    elif ratio_deuda <= 0.30:
        estado_deu, icono_deu = "warning", "⚠️"
    else:
        estado_deu, icono_deu = "error", "🚨"
    indicadores.append({
        "nombre": "Cuotas de deuda / ingresos",
        "valor": f"{ratio_deuda:.1%}",
        "estado": estado_deu,
        "icono": icono_deu,
        "descripcion": (
            "Porcentaje del ingreso comprometido en el pago de deudas (cuotas, tarjetas, préstamos). "
            "Referencia internacional: ≤15% saludable · 15-30% moderado · >30% sobreendeudado."
        ),
        "benchmark": "≤ 15%",
    })

    # 5. Índice de libertad financiera (ingreso restante después de gastos + deudas)
    libre = sueldo - total_gastos - deuda_mensual
    ratio_libre = libre / sueldo if sueldo > 0 else 0
    if ratio_libre >= 0.30:
        estado_lib, icono_lib = "ok", "✅"
    elif ratio_libre >= 0.15:
        estado_lib, icono_lib = "warning", "⚠️"
    else:
        estado_lib, icono_lib = "error", "🚨"
    indicadores.append({
        "nombre": "Margen financiero libre",
        "valor": f"{ratio_libre:.1%}",
        "estado": estado_lib,
        "icono": icono_lib,
        "descripcion": (
            "Porcentaje del ingreso libre tras cubrir gastos fijos y deudas. "
            "Refleja la flexibilidad ante imprevistos y la capacidad real de inversión."
        ),
        "benchmark": "≥ 30%",
    })

    return indicadores


@st.cache_data(ttl=3600)
def fetch_cotizaciones():
    """Trae cotizaciones de dolarapi.com. Devuelve dict con datos, "error_ssl" para fallas
    de certificado, o None para otros fallos de red/parseo."""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r1 = requests.get("https://dolarapi.com/v1/dolares", headers=headers, timeout=5)
        r2 = requests.get("https://dolarapi.com/v1/cotizaciones/eur", headers=headers, timeout=5)
        dolares = r1.json()
        eur = r2.json()
        usd_por_casa = {d.get("casa"): float(d["venta"]) for d in dolares if d.get("venta")}
        return {
            "USD": usd_por_casa,
            "EUR": float(eur.get("venta", 0)) or None,
            "actualizado": dolares[0].get("fechaActualizacion") if dolares else None,
        }
    except requests.exceptions.SSLError:
        return "error_ssl"
    except (requests.RequestException, ValueError, KeyError):
        return None


@st.cache_data
def build_excel(rows, perfil_data: tuple = ()):
    """
    Genera Excel con dos pestañas:
      - 'Ruta Crítica': tabla de objetivos enriquecidos
      - 'Perfil del Inversor': resumen del Risk Score y scoring por dimensión
    """
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        wb = writer.book

        # ── Hoja 1: Ruta Crítica ───────────────────────────────────────────
        df_reporte = pd.DataFrame(list(rows), columns=EXPORT_COLUMNS)
        df_reporte.to_excel(writer, index=False, sheet_name="Ruta Crítica")
        ws1 = writer.sheets["Ruta Crítica"]
        hdr_fmt = wb.add_format({'bold': True, 'bg_color': '#1a1a2e', 'font_color': '#FFFFFF', 'border': 1})
        for col_num, col_name in enumerate(EXPORT_COLUMNS):
            ws1.write(0, col_num, col_name, hdr_fmt)
        ws1.set_column(0, len(EXPORT_COLUMNS) - 1, 20)

        # ── Hoja 2: Perfil del Inversor ────────────────────────────────────
        if perfil_data:
            (rs, label, objetivo, horizonte, conocimiento,
             s_tolerancia, s_capacidad, s_horizonte, s_conocimiento, s_objetivo) = perfil_data

            titulo_fmt  = wb.add_format({'bold': True, 'font_size': 14, 'bg_color': '#1a1a2e',
                                          'font_color': '#FFFFFF', 'border': 1, 'align': 'center'})
            seccion_fmt = wb.add_format({'bold': True, 'bg_color': '#16213e', 'font_color': '#FFFFFF', 'border': 1})
            label_fmt   = wb.add_format({'bold': True, 'bg_color': '#F5F5F5', 'border': 1})
            valor_fmt   = wb.add_format({'border': 1, 'align': 'right'})
            pct_fmt     = wb.add_format({'border': 1, 'align': 'right', 'num_format': '0.0"%"'})

            ws2 = wb.add_worksheet("Perfil del Inversor")
            ws2.set_column(0, 0, 38)
            ws2.set_column(1, 1, 22)

            ws2.merge_range('A1:B1', '💰 Perfil del Inversor — Ruta Crítica Financiera', titulo_fmt)
            filas_perfil = [
                ("RESULTADO GLOBAL", None),
                ("Risk Score (0–100)", rs),
                ("Clasificación", label),
                ("Objetivo financiero", objetivo),
                ("Horizonte temporal", horizonte),
                ("Conocimiento financiero (score)", conocimiento),
                ("", None),
                ("SCORING POR DIMENSIÓN", None),
                (f"Tolerancia psicológica  (peso {int(PESO_TOLERANCIA*100)}%)", round(s_tolerancia, 1)),
                (f"Capacidad financiera    (peso {int(PESO_CAPACIDAD*100)}%)", round(s_capacidad, 1)),
                (f"Horizonte temporal      (peso {int(PESO_HORIZONTE*100)}%)", round(s_horizonte, 1)),
                (f"Conocimiento financiero (peso {int(PESO_CONOCIMIENTO*100)}%)", round(s_conocimiento, 1)),
                (f"Objetivo financiero     (peso {int(PESO_OBJETIVO*100)}%)", round(s_objetivo, 1)),
            ]
            for i, (k, v) in enumerate(filas_perfil, start=1):
                if v is None:
                    ws2.write(i, 0, k, seccion_fmt)
                    ws2.write(i, 1, "", seccion_fmt)
                else:
                    ws2.write(i, 0, k, label_fmt)
                    fmt = pct_fmt if isinstance(v, float) and k != "Risk Score (0–100)" and "clasificación" not in k.lower() and "objetivo" not in k.lower() and "horizonte" not in k.lower() else valor_fmt
                    ws2.write(i, 1, v, fmt)

    return buf.getvalue()


st.set_page_config(layout="wide", page_title="Ruta Crítica Financiera", page_icon="💰")

if 'objetivos' not in st.session_state:
    st.session_state.objetivos = []
if 'supuestos' not in st.session_state:
    st.session_state.supuestos = {m: dict(v) for m, v in SUPUESTOS_DEFAULT.items()}
if 'tc_USD' not in st.session_state:
    st.session_state.tc_USD = TIPOS_CAMBIO_DEFAULT["USD"]
if 'tc_EUR' not in st.session_state:
    st.session_state.tc_EUR = TIPOS_CAMBIO_DEFAULT["EUR"]
if 'tc_actualizado' not in st.session_state:
    st.session_state.tc_actualizado = None
if 'fx_msg' not in st.session_state:
    st.session_state.fx_msg = None
if 'config_msg' not in st.session_state:
    st.session_state.config_msg = None
# Perfil avanzado — persiste entre reruns
if 'perfil_completo' not in st.session_state:
    st.session_state.perfil_completo = False
if 'risk_score' not in st.session_state:
    st.session_state.risk_score = 50.0
if 'objetivo_financiero' not in st.session_state:
    st.session_state.objetivo_financiero = "Crecimiento patrimonial"
if 'horizonte_perfil' not in st.session_state:
    st.session_state.horizonte_perfil = "3 a 5 años"
if 'conocimiento_score' not in st.session_state:
    st.session_state.conocimiento_score = 50.0
# Scores parciales para el reporte Excel
for _k, _v in [('score_tolerancia', 50.0), ('score_capacidad', 50.0),
               ('score_horizonte', 50.0), ('score_conocimiento', 50.0), ('score_objetivo', 50.0)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


def serializar_config():
    """Devuelve bytes JSON con el estado persistible del usuario."""
    payload = {
        "version": 1,
        "objetivos": st.session_state.objetivos,
        "supuestos": st.session_state.supuestos,
        "tc_USD": float(st.session_state.tc_USD),
        "tc_EUR": float(st.session_state.tc_EUR),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def cargar_config_callback():
    """on_change del file_uploader: parsea JSON y actualiza session_state + widget keys."""
    uploaded = st.session_state.get("config_upload")
    if uploaded is None:
        return
    try:
        config = json.loads(uploaded.getvalue())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        st.session_state.config_msg = ("error", f"Archivo inválido: {e}")
        return
    if not isinstance(config, dict):
        st.session_state.config_msg = ("error", "Formato JSON inválido (se esperaba un objeto).")
        return

    if isinstance(config.get("objetivos"), list):
        st.session_state.objetivos = config["objetivos"]

    if isinstance(config.get("supuestos"), dict):
        for m, vals in config["supuestos"].items():
            if m in MONEDAS and isinstance(vals, dict):
                if "inflacion" in vals:
                    val = float(vals["inflacion"])
                    st.session_state.supuestos[m]["inflacion"] = val
                    st.session_state[f"infl_{m}"] = val
                if "rendimiento" in vals:
                    val = float(vals["rendimiento"])
                    st.session_state.supuestos[m]["rendimiento"] = val
                    st.session_state[f"rend_{m}"] = val

    if "tc_USD" in config:
        st.session_state.tc_USD = float(config["tc_USD"])
    if "tc_EUR" in config:
        st.session_state.tc_EUR = float(config["tc_EUR"])

    cnt = len(st.session_state.objetivos)
    st.session_state.config_msg = (
        "success",
        f"Configuración cargada: {cnt} objetivo{'s' if cnt != 1 else ''}.",
    )


def actualizar_cotizaciones_callback():
    """on_click: corre ANTES de re-instanciar widgets, así puede mutar tc_USD/tc_EUR."""
    data = fetch_cotizaciones()
    if data == "error_ssl":
        st.session_state.fx_msg = ("warning",
            "Error de certificado SSL al contactar dolarapi.com. "
            "Revisá tus certificados del sistema o ingresá los valores manualmente.")
        return
    if data is None:
        st.session_state.fx_msg = ("warning",
            "No se pudo conectar a dolarapi.com. Se mantienen los valores manuales.")
        return
    casa = st.session_state.get("casa_dolar", "bolsa")
    usd = data["USD"].get(casa)
    if usd:
        st.session_state.tc_USD = float(usd)
    if data.get("EUR"):
        st.session_state.tc_EUR = float(data["EUR"])
    st.session_state.tc_actualizado = data.get("actualizado")
    st.session_state.fx_msg = ("success",
        f"Cotizaciones actualizadas desde dolarapi.com ({casa}).")

st.title("💰 Planificador de Ruta Crítica Financiera")
st.markdown("Gestión de ahorro por **cascada de prioridades estratégica** con recomendación de inversión.")

# ── Mejora 2: Guía de flujo al inicio ────────────────────────────────────────
st.markdown("""
<div style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 4px 0;">
  <div style="flex:1;min-width:130px;background:#1a1a2e;border-radius:10px;padding:12px 10px;text-align:center;">
    <div style="font-size:22px;">🧠</div>
    <div style="font-size:13px;font-weight:700;color:#fff;margin-top:4px;">① Perfil</div>
    <div style="font-size:11px;color:#aaa;">Conocé tu Risk Score</div>
  </div>
  <div style="flex:0;display:flex;align-items:center;color:#555;font-size:20px;padding:0 4px;">→</div>
  <div style="flex:1;min-width:130px;background:#1a1a2e;border-radius:10px;padding:12px 10px;text-align:center;">
    <div style="font-size:22px;">💵</div>
    <div style="font-size:13px;font-weight:700;color:#fff;margin-top:4px;">② Ingresos</div>
    <div style="font-size:11px;color:#aaa;">Tu flujo de caja</div>
  </div>
  <div style="flex:0;display:flex;align-items:center;color:#555;font-size:20px;padding:0 4px;">→</div>
  <div style="flex:1;min-width:130px;background:#1a1a2e;border-radius:10px;padding:12px 10px;text-align:center;">
    <div style="font-size:22px;">🎯</div>
    <div style="font-size:13px;font-weight:700;color:#fff;margin-top:4px;">③ Metas</div>
    <div style="font-size:11px;color:#aaa;">Tus objetivos</div>
  </div>
  <div style="flex:0;display:flex;align-items:center;color:#555;font-size:20px;padding:0 4px;">→</div>
  <div style="flex:1;min-width:130px;background:#1a1a2e;border-radius:10px;padding:12px 10px;text-align:center;">
    <div style="font-size:22px;">📊</div>
    <div style="font-size:13px;font-weight:700;color:#fff;margin-top:4px;">④ Monitor</div>
    <div style="font-size:11px;color:#aaa;">Seguí tu ruta crítica</div>
  </div>
</div>
""", unsafe_allow_html=True)
st.divider()

st.header("① Perfil de Inversor Avanzado")
st.markdown(
    "Completá el cuestionario para obtener tu **Risk Score personalizado** y recomendaciones precisas. "
    "Este análisis combina tu tolerancia psicológica, capacidad financiera, horizonte temporal, "
    "conocimiento y objetivos — igual que los sistemas utilizados por robo-advisors y bancos digitales."
)

with st.expander("📋 Completar / actualizar mi perfil de inversor", expanded=not st.session_state.perfil_completo):

    # ── Mejora 1: indicador de progreso ──────────────────────────────────────
    st.markdown(
        "<div style='background:#1a1a2e;border-radius:8px;padding:10px 16px;margin-bottom:12px;"
        "display:flex;justify-content:space-between;align-items:center;'>"
        "<span style='color:#aaa;font-size:13px;'>⏱ Tiempo estimado: <b style='color:#fff'>2 minutos</b></span>"
        "<span style='color:#aaa;font-size:13px;'>5 bloques · 12 preguntas</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    prog_cols = st.columns(5)
    _pasos = ["① Tolerancia", "② Capacidad", "③ Horizonte", "④ Conocimiento", "⑤ Objetivo"]
    for i, label in enumerate(_pasos):
        prog_cols[i].markdown(
            f"<div style='text-align:center;font-size:11px;"
            f"color:#2ECC71;font-weight:600;border-bottom:2px solid #2ECC71;padding-bottom:4px;'>"
            f"{label}</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.subheader("① Tolerancia psicológica al riesgo  ·  35% del score")
    col_t1, col_t2 = st.columns(2)

    with col_t1:
        r_10 = st.radio(
            "Si tu cartera baja **10%** en un mes, ¿qué hacés?",
            ["Vendo todo inmediatamente", "Me preocupo pero no hago nada",
             "Espero y monitoreo", "Compro más (oportunidad)"],
            key="r_10",
        )
        r_20 = st.radio(
            "Si baja **20%**, ¿qué hacés?",
            ["Vendo todo inmediatamente", "Vendo una parte para reducir pérdidas",
             "Mantengo sin cambios", "Compro más"],
            key="r_20",
        )
        r_30 = st.radio(
            "Si baja **30%**, ¿qué hacés?",
            ["Vendo todo de inmediato", "Vendo la mitad",
             "Mantengo y espero recuperación", "Compro más agresivamente"],
            key="r_30",
        )

    with col_t2:
        r_pref = st.radio(
            "¿Qué te importa más al invertir?",
            ["No perder dinero bajo ninguna circunstancia",
             "Un poco de crecimiento con mínima volatilidad",
             "Balance entre estabilidad y rendimiento",
             "Maximizar rendimiento aunque haya caídas fuertes"],
            key="r_pref",
        )
        r_crisis = st.radio(
            "¿Cómo reaccionaste en crisis financieras anteriores (2018, 2020, etc.)?",
            ["Vendí y salí del mercado", "Me angustié mucho pero no hice nada",
             "Lo tomé con calma", "Aproveché para comprar más",
             "No tenía inversiones aún"],
            key="r_crisis",
        )

    # Scoring tolerancia (0-100)
    _t_10   = {"Vendo todo inmediatamente": 0, "Me preocupo pero no hago nada": 33,
               "Espero y monitoreo": 67, "Compro más (oportunidad)": 100}
    _t_20   = {"Vendo todo inmediatamente": 0, "Vendo una parte para reducir pérdidas": 25,
               "Mantengo sin cambios": 65, "Compro más": 100}
    _t_30   = {"Vendo todo de inmediato": 0, "Vendo la mitad": 20,
               "Mantengo y espero recuperación": 60, "Compro más agresivamente": 100}
    _t_pref = {"No perder dinero bajo ninguna circunstancia": 0,
               "Un poco de crecimiento con mínima volatilidad": 30,
               "Balance entre estabilidad y rendimiento": 60,
               "Maximizar rendimiento aunque haya caídas fuertes": 100}
    _t_cris = {"Vendí y salí del mercado": 0, "Me angustié mucho pero no hice nada": 25,
               "Lo tomé con calma": 60, "Aproveché para comprar más": 100,
               "No tenía inversiones aún": 50}

    score_tolerancia = (
        _t_10.get(r_10, 50) * 0.20 +
        _t_20.get(r_20, 50) * 0.25 +
        _t_30.get(r_30, 50) * 0.25 +
        _t_pref.get(r_pref, 50) * 0.20 +
        _t_cris.get(r_crisis, 50) * 0.10
    )

    st.divider()
    st.subheader("② Capacidad financiera para asumir riesgo  ·  25% del score")
    cf1, cf2, cf3 = st.columns(3)

    with cf1:
        r_emerg = st.radio(
            "¿Tenés fondo de emergencia (3-6 meses de gastos)?",
            ["No tengo", "Menos de 1 mes", "1 a 3 meses", "3 a 6 meses", "Más de 6 meses"],
            key="r_emerg",
        )
        r_estab = st.radio(
            "Estabilidad laboral / fuente de ingresos",
            ["Inestable / desempleo reciente", "Freelance / variable",
             "Relación de dependencia estable", "Múltiples fuentes de ingresos"],
            key="r_estab",
        )
    with cf2:
        r_deuda = st.radio(
            "Nivel de endeudamiento respecto a tus ingresos",
            ["Más del 50% de ingresos en deudas", "Entre 30% y 50%",
             "Entre 10% y 30%", "Menos del 10% o sin deudas"],
            key="r_deuda",
        )
        r_ahorro_pct = st.radio(
            "¿Qué porcentaje de tu ingreso ahorrás habitualmente?",
            ["No ahorro / gasto más de lo que gano", "Menos del 5%",
             "Entre 5% y 15%", "Entre 15% y 30%", "Más del 30%"],
            key="r_ahorro_pct",
        )
    with cf3:
        r_depend = st.radio(
            "Dependientes económicos a tu cargo",
            ["3 o más", "2", "1", "Ninguno"],
            key="r_depend",
        )

    _c_emerg  = {"No tengo": 0, "Menos de 1 mes": 15, "1 a 3 meses": 40,
                 "3 a 6 meses": 75, "Más de 6 meses": 100}
    _c_estab  = {"Inestable / desempleo reciente": 0, "Freelance / variable": 35,
                 "Relación de dependencia estable": 70, "Múltiples fuentes de ingresos": 100}
    _c_deuda  = {"Más del 50% de ingresos en deudas": 0, "Entre 30% y 50%": 25,
                 "Entre 10% y 30%": 60, "Menos del 10% o sin deudas": 100}
    _c_aho    = {"No ahorro / gasto más de lo que gano": 0, "Menos del 5%": 20,
                 "Entre 5% y 15%": 50, "Entre 15% y 30%": 80, "Más del 30%": 100}
    _c_dep    = {"3 o más": 10, "2": 40, "1": 65, "Ninguno": 100}

    score_capacidad = (
        _c_emerg.get(r_emerg, 50)   * 0.30 +
        _c_estab.get(r_estab, 50)   * 0.25 +
        _c_deuda.get(r_deuda, 50)   * 0.25 +
        _c_aho.get(r_ahorro_pct, 50) * 0.10 +
        _c_dep.get(r_depend, 50)    * 0.10
    )

    st.divider()
    st.subheader("③ Horizonte temporal  ·  20% del score")
    r_horizonte = st.select_slider(
        "¿En cuánto tiempo necesitás o querés disponer del capital invertido?",
        options=["Menos de 1 año", "1 a 3 años", "3 a 5 años", "5 a 10 años", "Más de 10 años"],
        value="3 a 5 años",
        key="r_horizonte",
    )
    _h_score = {"Menos de 1 año": 5, "1 a 3 años": 25, "3 a 5 años": 55,
                "5 a 10 años": 80, "Más de 10 años": 100}
    score_horizonte = float(_h_score.get(r_horizonte, 50))

    st.divider()
    st.subheader("④ Conocimiento financiero  ·  10% del score")
    st.caption("Marcá los instrumentos que conocés y sabés cómo funcionan (no solo que existen).")
    k1, k2, k3 = st.columns(3)
    con_acciones   = k1.checkbox("Acciones (compra/venta, dividendos)", key="con_acc")
    con_bonos      = k1.checkbox("Bonos (TIR, duration, calificación)", key="con_bon")
    con_etf        = k2.checkbox("ETFs (estructura, tracking error)", key="con_etf")
    con_fci        = k2.checkbox("Fondos Comunes de Inversión", key="con_fci")
    con_divs       = k3.checkbox("Diversificación y correlación de activos", key="con_div")
    con_inflacion  = k3.checkbox("Efecto de la inflación en rendimientos reales", key="con_inf")

    _conocimientos = [con_acciones, con_bonos, con_etf, con_fci, con_divs, con_inflacion]
    score_conocimiento = (sum(_conocimientos) / len(_conocimientos)) * 100

    st.divider()
    st.subheader("⑤ Objetivo financiero principal  ·  10% del score")
    r_objetivo = st.selectbox(
        "¿Cuál es el objetivo principal de esta inversión?",
        OBJETIVOS_FINANCIEROS,
        index=4,
        key="r_objetivo",
    )
    _base_obj = 50.0
    score_objetivo = max(0.0, min(100.0, _base_obj + OBJETIVO_SCORE_AJUSTE.get(r_objetivo, 0)))

    # ── Cálculo del Risk Score ponderado ─────────────────────────────────────
    raw_score = (
        score_tolerancia   * PESO_TOLERANCIA   +
        score_capacidad    * PESO_CAPACIDAD    +
        score_horizonte    * PESO_HORIZONTE    +
        score_conocimiento * PESO_CONOCIMIENTO +
        score_objetivo     * PESO_OBJETIVO
    )
    risk_score_calculado = round(max(0.0, min(100.0, raw_score)), 1)
    perfil_label, perfil_emoji = clasificar_perfil(risk_score_calculado)

    st.divider()
    if st.button("✅ Calcular mi Risk Score", type="primary", use_container_width=True):
        st.session_state.risk_score           = risk_score_calculado
        st.session_state.objetivo_financiero  = r_objetivo
        st.session_state.horizonte_perfil     = r_horizonte
        st.session_state.conocimiento_score   = score_conocimiento
        st.session_state.perfil_completo      = True
        # Guardar scores parciales para el Excel
        st.session_state.score_tolerancia     = round(score_tolerancia, 1)
        st.session_state.score_capacidad      = round(score_capacidad, 1)
        st.session_state.score_horizonte      = round(score_horizonte, 1)
        st.session_state.score_conocimiento   = round(score_conocimiento, 1)
        st.session_state.score_objetivo       = round(score_objetivo, 1)
        # Mejora 4: feedback inmediato
        _lbl, _emo = clasificar_perfil(risk_score_calculado)
        st.toast(f"{_emo} Perfil calculado: **{_lbl}** · Score {risk_score_calculado}", icon="✅")
        st.rerun()

# ── Tarjeta de resultados del perfil ─────────────────────────────────────────
risk_score          = st.session_state.risk_score
objetivo_financiero = st.session_state.objetivo_financiero
horizonte_perfil    = st.session_state.horizonte_perfil
conocimiento_score  = st.session_state.conocimiento_score
perfil_label_show, perfil_emoji_show = clasificar_perfil(risk_score)

# Mejora 3: si el perfil no fue completado, mostrar aviso en lugar del score default
if not st.session_state.perfil_completo:
    st.info(
        "👆 **Completá el cuestionario de arriba** para ver tu Risk Score real y recibir "
        "recomendaciones de inversión personalizadas. El resultado aparecerá aquí."
    )
else:
    _score_color = (
        "#2196F3" if risk_score <= 20 else
        "#4CAF50" if risk_score <= 40 else
        "#FFC107" if risk_score <= 60 else
        "#FF9800" if risk_score <= 80 else "#F44336"
    )
    _bar_pct = int(risk_score)

    st.markdown(f"""
<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border-radius:16px;padding:24px 28px;margin-bottom:16px;">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
    <div>
      <div style="font-size:13px;color:#aaa;letter-spacing:1px;text-transform:uppercase;">Risk Score</div>
      <div style="font-size:52px;font-weight:900;color:{_score_color};line-height:1.1;">{risk_score}</div>
      <div style="font-size:20px;color:#fff;font-weight:600;">{perfil_emoji_show} {perfil_label_show}</div>
    </div>
    <div style="flex:1;min-width:220px;">
      <div style="background:#333;border-radius:8px;height:12px;margin-bottom:16px;">
        <div style="background:{_score_color};width:{_bar_pct}%;height:100%;border-radius:8px;transition:width 0.4s;"></div>
      </div>
      <table style="width:100%;color:#ddd;font-size:14px;border-collapse:collapse;">
        <tr><td style="padding:4px 0;color:#aaa;">🎯 Objetivo</td><td style="text-align:right;color:#fff;">{objetivo_financiero}</td></tr>
        <tr><td style="padding:4px 0;color:#aaa;">⏳ Horizonte</td><td style="text-align:right;color:#fff;">{horizonte_perfil}</td></tr>
        <tr><td style="padding:4px 0;color:#aaa;">📚 Conocimiento</td><td style="text-align:right;color:#fff;">{int(conocimiento_score)}/100</td></tr>
      </table>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    # Recomendación general del perfil
    _horizonte_meses_map = {
        "Menos de 1 año": 6, "1 a 3 años": 24, "3 a 5 años": 48,
        "5 a 10 años": 84, "Más de 10 años": 144,
    }
    horizonte_meses_perfil = _horizonte_meses_map.get(horizonte_perfil, 48)
    rec_general = recomendar_instrumento_avanzado(
        risk_score, horizonte_meses_perfil, objetivo_financiero, conocimiento_score, "ARS"
    )

    with st.container(border=True):
        st.markdown(f"### {rec_general['emoji']} {rec_general['tipo']}")
        st.markdown(rec_general["descripcion"])
        if rec_general.get("advertencias"):
            for adv in rec_general["advertencias"]:
                st.caption(adv)
        # Tabla de allocations del perfil general
        alloc_cols = st.columns(len(rec_general["allocations"]))
        for i, a in enumerate(rec_general["allocations"]):
            alloc_cols[i].markdown(
                f"<div style='border-left:3px solid {a['color']};padding:6px 10px;'>"
                f"<div style='font-size:18px;font-weight:800;color:{a['color']};'>{a['pct']}%</div>"
                f"<div style='font-size:12px;font-weight:600;'>{a['nombre']}</div>"
                f"<div style='font-size:10px;color:#888;'>{a['clase']} · {a['riesgo']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

# Expone variables para uso en el resto de la app
perfil = perfil_label_show  # backward compat con secciones inferiores

with st.expander("⚙️ Supuestos macro y tipos de cambio", expanded=False):
    st.caption("Inflación y rendimiento nominales anuales. Editá según tu contexto.")
    cols = st.columns(3)
    for i, m in enumerate(MONEDAS):
        with cols[i]:
            st.markdown(f"**{m}**")
            st.session_state.supuestos[m]["inflacion"] = st.number_input(
                f"Inflación anual % ({m})",
                value=float(st.session_state.supuestos[m]["inflacion"]),
                step=0.5, key=f"infl_{m}",
            )
            st.session_state.supuestos[m]["rendimiento"] = st.number_input(
                f"Rendimiento anual % ({m})",
                value=float(st.session_state.supuestos[m]["rendimiento"]),
                step=0.5, key=f"rend_{m}",
            )

    st.divider()
    st.markdown("**Tipos de cambio** (ARS por 1 unidad)")
    fx_cols = st.columns([1, 1, 1.4])
    fx_cols[0].number_input("USD → ARS", step=10.0, key="tc_USD")
    fx_cols[1].number_input("EUR → ARS", step=10.0, key="tc_EUR")
    fx_cols[2].selectbox("Casa para actualizar USD", CASAS_DOLAR, index=2, key="casa_dolar")

    st.button("🔄 Actualizar cotizaciones desde dolarapi.com",
              on_click=actualizar_cotizaciones_callback)

    if st.session_state.fx_msg:
        tipo, msg = st.session_state.fx_msg
        getattr(st, tipo)(msg)

    if st.session_state.tc_actualizado:
        st.caption(f"Última actualización: {st.session_state.tc_actualizado}")
    else:
        st.caption("Cotizaciones manuales (sin actualización remota).")

with st.expander("💾 Guardar / Cargar configuración", expanded=False):
    st.caption("Descargá tus objetivos y supuestos como JSON. Cargá un archivo previo para restaurarlos.")
    cfg_cols = st.columns([1, 1])
    cfg_cols[0].download_button(
        label="📥 Descargar configuración",
        data=serializar_config(),
        file_name="configuracion_finanzas.json",
        mime="application/json",
        use_container_width=True,
    )
    cfg_cols[1].file_uploader(
        "📂 Cargar configuración",
        type=["json"],
        key="config_upload",
        on_change=cargar_config_callback,
        label_visibility="collapsed",
    )
    if st.session_state.config_msg:
        tipo, msg = st.session_state.config_msg
        getattr(st, tipo)(msg)

st.divider()

supuestos = st.session_state.supuestos
tipos_cambio = {
    "ARS": 1.0,
    "USD": float(st.session_state.tc_USD),
    "EUR": float(st.session_state.tc_EUR),
}

col_inputs, col_visual = st.columns([1.2, 1], gap="large")

with col_inputs:
    st.header("② Flujo de Caja Mensual")
    col_moneda, col_sueldo = st.columns([1, 2])
    with col_moneda:
        moneda = st.selectbox("Moneda del ingreso", MONEDAS, index=0)
    with col_sueldo:
        sueldo = st.number_input(f"Sueldo Neto Mensual ({moneda})", min_value=0.0, step=1000.0)

    total_gastos = st.number_input(f"Total Gastos Fijos Mensuales ({moneda})", min_value=0.0, step=1000.0)
    disponible_bruto = float(sueldo - total_gastos)

    st.divider()
    st.subheader("💡 Capacidad de Ahorro")
    ahorro_dispuesto = 0.0
    if sueldo > 0:
        if disponible_bruto > 0:
            st.info(f"Excedente disponible: **{moneda} {disponible_bruto:,.2f}**")
            ahorro_dispuesto = st.slider(
                "¿Cuánto vas a destinar al ahorro/inversión?",
                0.0, disponible_bruto, value=disponible_bruto * DEFAULT_AHORRO_RATIO, step=500.0,
            )
        else:
            st.error("🚨 Sin margen de ahorro.")

with col_visual:
    st.subheader("Distribución Mensual")
    if sueldo > 0:
        remanente_ocio = max(0.0, disponible_bruto - ahorro_dispuesto)
        fig = go.Figure(data=[go.Pie(
            labels=['Gastos Fijos', 'Ahorro Destinado', 'Remanente Ocio'],
            values=[total_gastos, ahorro_dispuesto, remanente_ocio],
            hole=.4, marker_colors=['#262626', '#2ECC71', '#BDC3C7'],
        )])
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=300)
        st.plotly_chart(fig, use_container_width=True)

if sueldo > 0:
    st.subheader("🩺 Diagnóstico de Salud Financiera")

    diag_col1, diag_col2 = st.columns(2)
    with diag_col1:
        fondo_emerg_monto = st.number_input(
            f"Fondo de emergencia acumulado total ({moneda})",
            min_value=0.0, step=1000.0,
            help="Capital líquido disponible para emergencias (cuenta bancaria, FCI money market). "
                 "NO incluyas inversiones que tardan en rescatarse.",
        )
    with diag_col2:
        deuda_mensual_input = st.number_input(
            f"Total cuotas de deuda por mes ({moneda})",
            min_value=0.0, step=500.0,
            help="Suma de todas las cuotas que pagás por mes: créditos, tarjetas en cuotas, préstamos. "
                 "No incluyas gastos corrientes de tarjeta.",
        )

    # Calcular meses de cobertura del fondo de emergencia
    gastos_para_fe = total_gastos if total_gastos > 0 else 1.0
    meses_fondo = fondo_emerg_monto / gastos_para_fe if gastos_para_fe > 0 else 0.0

    indicadores = calcular_indicadores_salud(
        sueldo, total_gastos, ahorro_dispuesto, meses_fondo, deuda_mensual_input
    )

    # Alerta crítica: fondo de emergencia inexistente antes de invertir
    if meses_fondo < 1 and ahorro_dispuesto > 0:
        st.error(
            "🚨 **Prioridad crítica:** No tenés fondo de emergencia. "
            "Antes de invertir en cualquier instrumento, acumulá al menos 3 meses de gastos "
            "en un FCI money market o cuenta remunerada. Sin este colchón, cualquier imprevisto "
            "te obligaría a vender inversiones en el peor momento."
        )

    ind_cols = st.columns(len(indicadores))
    color_estado = {"ok": "#2ECC71", "warning": "#F1C40F", "error": "#E74C3C"}
    for i, ind in enumerate(indicadores):
        col = ind_cols[i]
        c = color_estado[ind["estado"]]
        col.markdown(
            f"""<div style='border:1px solid {c};border-radius:10px;padding:12px 10px;text-align:center;'>
            <div style='font-size:22px;'>{ind['icono']}</div>
            <div style='font-size:11px;color:#888;margin-top:4px;'>{ind['nombre']}</div>
            <div style='font-size:20px;font-weight:700;color:{c};'>{ind['valor']}</div>
            <div style='font-size:10px;color:#aaa;margin-top:2px;'>benchmark: {ind['benchmark']}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        col.caption(ind["descripcion"])

    # Tips adicionales (conservados del original)
    st.divider()
    st.subheader("🤖 Análisis Automático")
    tips = []
    ratio_gastos = total_gastos / sueldo
    ratio_ahorro = ahorro_dispuesto / sueldo

    if disponible_bruto <= 0:
        tips.append(("error", "🚨 Déficit mensual detectado: tus gastos superan tus ingresos."))
    if ratio_gastos > RATIO_GASTOS_ALTO:
        tips.append(("warning", "⚠️ Tus gastos fijos superan el 70% de tu ingreso. La regla 50/30/20 recomienda no más del 50% en necesidades."))
    if ratio_ahorro < RATIO_AHORRO_BAJO:
        tips.append(("info", "📉 Estás ahorrando menos del 10% de tu ingreso. Intentá llevar ese ratio al 20% progresivamente."))
    if ratio_ahorro >= RATIO_AHORRO_OBJETIVO:
        tips.append(("success", "✅ Excelente tasa de ahorro. Estás por encima del benchmark del 20% recomendado."))

    if tips:
        for tipo, msg in tips:
            getattr(st, tipo)(msg)
    else:
        st.success("Tu perfil financiero está equilibrado.")

else:
    st.info("📋 Ingresá tu sueldo en la sección ② para ver tu diagnóstico financiero.")
    fondo_emerg_monto = 0.0
    deuda_mensual_input = 0.0

st.divider()

st.header("③ Definición y Gestión de Objetivos")

# ── Mejora 6: alerta si no hay meta de fondo de emergencia ────────────────────
if st.session_state.objetivos:
    tiene_fondo = any(
        o.get("Categoría") == "Fondo de Emergencia"
        for o in st.session_state.objetivos
    )
    if not tiene_fondo:
        st.warning(
            "⚠️ **Sin fondo de emergencia en tu ruta.** "
            "Los asesores financieros coinciden: antes de invertir en cualquier instrumento, "
            "es necesario tener 3-6 meses de gastos en activos líquidos. "
            "Considerá agregar una meta de categoría **Fondo de Emergencia** con prioridad Alta."
        )

col_form, col_lista = st.columns([1, 2.5])

with col_form:
    with st.form("nuevo_objetivo", clear_on_submit=True):
        st.subheader("Añadir Nueva Meta")
        nombre_obj = st.text_input("Nombre de la Meta")
        categoria = st.selectbox("Categoría", CATEGORIAS)
        col_m, col_costo = st.columns([1, 2])
        moneda_meta = col_m.selectbox("Moneda", MONEDAS, index=MONEDAS.index(moneda))
        costo_total = col_costo.number_input(
            "Costo Total (hoy)", min_value=0.0, step=1000.0, format="%.2f"
        )
        ahorro_previo = st.number_input(
            "Ahorrado hoy (misma moneda)", min_value=0.0,
            max_value=float(costo_total) if costo_total > 0 else 1_000_000_000.0,
            step=1000.0, format="%.2f"
        )
        cp1, cp2 = st.columns([2, 1])
        plazo_num = cp1.number_input("Plazo deseado", min_value=1, value=12)
        plazo_unit = cp2.selectbox("Unidad", ["Meses", "Años"])
        prioridad = st.select_slider("Prioridad", options=PRIORIDADES, value="Media")

        if st.form_submit_button("Añadir a la Ruta"):
            if not nombre_obj.strip():
                st.warning("Falta el nombre de la meta.")
            elif costo_total <= 0:
                st.warning("El costo total debe ser mayor a 0.")
            else:
                meses = plazo_num if plazo_unit == "Meses" else plazo_num * 12
                st.session_state.objetivos.append({
                    "Meta": nombre_obj.strip(),
                    "Categoría": categoria,
                    "Prioridad": prioridad,
                    "Moneda": moneda_meta,
                    "Costo Total": float(costo_total),
                    "Ya Ahorrado": float(min(ahorro_previo, costo_total)),
                    "Plazo (Meses)": int(meses),
                })
                st.rerun()

objetivos_enriquecidos = []

with col_lista:
    if st.session_state.objetivos:
        df_base = pd.DataFrame(st.session_state.objetivos)
        if "Moneda" not in df_base.columns:
            df_base["Moneda"] = moneda
        else:
            df_base["Moneda"] = df_base["Moneda"].fillna(moneda)

        df_base['Cuota Requerida'] = [
            calcular_cuota_meta(o, supuestos)["cuota_ideal"]
            for o in df_base.to_dict('records')
        ]

        st.subheader("Listado Estratégico")

        # Agregar columna de selección para borrar
        df_con_borrar = df_base.copy()
        df_con_borrar.insert(0, "🗑️ Borrar", False)

        edited_df = st.data_editor(
            df_con_borrar, num_rows="dynamic", use_container_width=True,
            column_config={
                "🗑️ Borrar": st.column_config.CheckboxColumn(
                    "🗑️", help="Marcá para eliminar esta meta", default=False, width="small"
                ),
                "Categoría": st.column_config.SelectboxColumn("Categoría", options=CATEGORIAS),
                "Prioridad": st.column_config.SelectboxColumn("Prioridad", options=PRIORIDADES),
                "Moneda": st.column_config.SelectboxColumn("Moneda", options=MONEDAS),
                "Costo Total": st.column_config.NumberColumn("Costo Total", format="%.2f"),
                "Ya Ahorrado": st.column_config.NumberColumn("Ahorrado Hoy", format="%.2f"),
                "Cuota Requerida": st.column_config.NumberColumn(
                    "Cuota Requerida", format="%.2f", disabled=True,
                    help="Cuota mensual estimada para llegar al costo futuro ajustado por inflación, "
                         "capitalizando al rendimiento de la moneda.",
                ),
            },
            key="editor_cascada_final",
        )

        # Botón para confirmar borrado de filas marcadas
        filas_a_borrar = edited_df[edited_df["🗑️ Borrar"] == True]
        if len(filas_a_borrar) > 0:
            nombres_a_borrar = filas_a_borrar["Meta"].tolist()
            st.warning(
                f"Vas a eliminar: **{', '.join(str(n) for n in nombres_a_borrar)}**"
            )
            if st.button("🗑️ Confirmar eliminación", type="primary", use_container_width=True):
                st.session_state.objetivos = [
                    o for o in st.session_state.objetivos
                    if o.get("Meta") not in nombres_a_borrar
                ]
                st.rerun()

        cleaned = edited_df.drop(columns=['Cuota Requerida', '🗑️ Borrar']).copy()
        cleaned["Moneda"] = cleaned["Moneda"].fillna(moneda)
        cleaned = cleaned.dropna(subset=["Meta", "Costo Total", "Plazo (Meses)"])
        cleaned = cleaned[cleaned["Meta"].astype(str).str.strip() != ""]
        if not cleaned.reset_index(drop=True).equals(df_base.drop(columns=['Cuota Requerida']).reset_index(drop=True)):
            st.session_state.objetivos = cleaned.to_dict('records')
            st.rerun()

        objs_sorted = sorted(st.session_state.objetivos, key=lambda x: PRIO_ORDER.get(x.get("Prioridad"), 3))
        ahorro_restante_ingreso = ahorro_dispuesto

        for obj in objs_sorted:
            cuota = calcular_cuota_meta(obj, supuestos)
            moneda_m = cuota["moneda_meta"]
            cuota_ideal_meta = cuota["cuota_ideal"]
            cuota_ideal_ingreso = convertir(cuota_ideal_meta, moneda_m, moneda, tipos_cambio)
            cuota_asignada_ingreso = min(ahorro_restante_ingreso, cuota_ideal_ingreso)
            ahorro_restante_ingreso -= cuota_asignada_ingreso
            cuota_asignada_meta = convertir(cuota_asignada_ingreso, moneda, moneda_m, tipos_cambio)

            objetivos_enriquecidos.append({
                **obj,
                "moneda_meta": moneda_m,
                "costo_futuro": cuota["costo_futuro"],
                "faltante_futuro": cuota["faltante_futuro"],
                "r_mensual": cuota["r_mensual"],
                "cuota_ideal_meta": cuota_ideal_meta,
                "cuota_asignada_meta": cuota_asignada_meta,
                "cuota_ideal_ingreso": cuota_ideal_ingreso,
                "cuota_asignada_ingreso": cuota_asignada_ingreso,
                "estado": estado_meta(cuota_asignada_meta, cuota_ideal_meta),
                # Mejora 3: objetivo derivado de la categoría de cada meta
                "objetivo_meta": CATEGORIA_A_OBJETIVO.get(
                    obj.get("Categoría", "Otro"), objetivo_financiero
                ),
                "instrumento": recomendar_instrumento(
                    obj.get("Plazo (Meses)", 0),
                    perfil,
                    risk_score=risk_score,
                    objetivo=CATEGORIA_A_OBJETIVO.get(
                        obj.get("Categoría", "Otro"), objetivo_financiero
                    ),
                    conocimiento_score=conocimiento_score,
                    moneda_meta=obj.get("Moneda", "ARS"),
                ),
            })

        st.info(f"💰 Ahorro sobrante tras cubrir prioridades: **{moneda} {ahorro_restante_ingreso:,.2f}**")
    else:
        st.info("Cargá una meta para ver la tabla.")

st.divider()

if objetivos_enriquecidos:
    st.header("④ Monitor de Asignación Real (Cascada)")

    # ── Mejora 4: Panel de análisis de escenarios ─────────────────────────────
    with st.expander("🔭 Análisis de Escenarios (What-If)", expanded=False):
        st.markdown(
            "Simulá cómo cambian tus metas ante distintos contextos económicos o de ahorro. "
            "Los cambios aquí son **solo para visualización** y no modifican tu planificación base."
        )
        sc1, sc2, sc3 = st.columns(3)
        delta_ahorro_pct = sc1.slider(
            "Cambio en ahorro mensual",
            min_value=-50, max_value=100, value=0, step=5,
            format="%d%%",
            help="Simulá qué pasa si ahorrás más o menos cada mes.",
        )
        delta_inflacion = sc2.slider(
            "Variación de inflación anual (pp)",
            min_value=-30, max_value=60, value=0, step=5,
            format="%+d pp",
            help="Puntos porcentuales adicionales sobre la inflación configurada.",
        )
        delta_rendimiento = sc3.slider(
            "Variación de rendimiento anual (pp)",
            min_value=-10, max_value=20, value=0, step=1,
            format="%+d pp",
            help="Puntos porcentuales adicionales sobre el rendimiento configurado.",
        )

        if delta_ahorro_pct != 0 or delta_inflacion != 0 or delta_rendimiento != 0:
            ahorro_escenario = ahorro_dispuesto * (1 + delta_ahorro_pct / 100)
            supuestos_escenario = {
                m: {
                    "inflacion":   v["inflacion"]   + delta_inflacion,
                    "rendimiento": v["rendimiento"] + delta_rendimiento,
                }
                for m, v in supuestos.items()
            }
            ahorro_rest_esc = ahorro_escenario
            resumen_esc = []
            for obj in sorted(st.session_state.objetivos, key=lambda x: PRIO_ORDER.get(x.get("Prioridad"), 3)):
                cuota_esc = calcular_cuota_meta(obj, supuestos_escenario)
                cuota_ideal_esc = cuota_esc["cuota_ideal"]
                cuota_ideal_ing_esc = convertir(cuota_ideal_esc, cuota_esc["moneda_meta"], moneda, tipos_cambio)
                asignada_ing_esc = min(ahorro_rest_esc, cuota_ideal_ing_esc)
                ahorro_rest_esc -= asignada_ing_esc
                asignada_meta_esc = convertir(asignada_ing_esc, moneda, cuota_esc["moneda_meta"], tipos_cambio)
                resumen_esc.append({
                    "Meta": obj["Meta"],
                    "Cuota ideal (escenario)": round(cuota_ideal_esc, 2),
                    "Asignada (escenario)": round(asignada_meta_esc, 2),
                    "Costo futuro (escenario)": round(cuota_esc["costo_futuro"], 2),
                    "Estado": estado_meta(asignada_meta_esc, cuota_ideal_esc),
                    "Moneda": cuota_esc["moneda_meta"],
                })
            df_esc = pd.DataFrame(resumen_esc)
            st.dataframe(df_esc, use_container_width=True, hide_index=True)
            st.caption(
                f"Escenario: ahorro {'+'if delta_ahorro_pct>=0 else ''}{delta_ahorro_pct}% · "
                f"inflación {'+'if delta_inflacion>=0 else ''}{delta_inflacion}pp · "
                f"rendimiento {'+'if delta_rendimiento>=0 else ''}{delta_rendimiento}pp"
            )
        else:
            st.info("Mové alguno de los sliders para ver el impacto en tus metas.")

    st.divider()

    num_filas = math.ceil(len(objetivos_enriquecidos) / OBJ_POR_FILA)

    for f in range(num_filas):
        cols = st.columns(OBJ_POR_FILA)
        for c in range(OBJ_POR_FILA):
            idx = f * OBJ_POR_FILA + c
            if idx >= len(objetivos_enriquecidos):
                continue
            o = objetivos_enriquecidos[idx]
            categoria_obj = o.get("Categoría", "Otro")
            color = COLOR_PRIORIDAD.get(o['Prioridad'], '#888')
            m_meta = o['moneda_meta']

            with cols[c]:
                with st.container(border=True):
                    # ── Encabezado ────────────────────────────────────────────
                    st.markdown(
                        f"### {o['Meta']} "
                        f"<span style='float:right; color:{color}; font-size:16px;'>"
                        f"{o['Prioridad']}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<span style='background:#eee; color:#444; padding:2px 8px; "
                        f"border-radius:8px; font-size:12px;'>{categoria_obj} · {m_meta}</span>",
                        unsafe_allow_html=True,
                    )

                    # ── Barra de progreso ─────────────────────────────────────
                    costo_total_val = float(o["Costo Total"])
                    ya_ahorrado_val = float(o["Ya Ahorrado"])
                    pct_actual = (ya_ahorrado_val / costo_total_val * 100) if costo_total_val > 0 else 0
                    pct_actual = min(pct_actual, 100)
                    bar_color = color

                    st.markdown(
                        f"<div style='margin:10px 0 4px 0;'>"
                        f"<div style='display:flex;justify-content:space-between;font-size:11px;color:#888;margin-bottom:3px;'>"
                        f"<span>Progreso actual</span>"
                        f"<span style='font-weight:700;color:{bar_color};'>{pct_actual:.1f}%</span>"
                        f"</div>"
                        f"<div style='background:#2a2a2a;border-radius:6px;height:10px;'>"
                        f"<div style='background:{bar_color};width:{pct_actual:.1f}%;height:100%;"
                        f"border-radius:6px;transition:width 0.4s;'></div>"
                        f"</div>"
                        f"<div style='display:flex;justify-content:space-between;font-size:10px;"
                        f"color:#666;margin-top:2px;'>"
                        f"<span>{fmt(ya_ahorrado_val, m_meta)} ahorrado</span>"
                        f"<span>Meta: {fmt(costo_total_val, m_meta)}</span>"
                        f"</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    # ── Bloque de asignación de cuotas ────────────────────────
                    cuota_ideal  = o['cuota_ideal_meta']
                    cuota_asign  = o['cuota_asignada_meta']
                    faltante     = o['faltante_futuro']
                    plazo_orig   = int(o.get("Plazo (Meses)", 0))
                    estado_val   = o['estado']

                    # Calcular meses reales a cuota asignada
                    meses_reales = meses_para_acumular(faltante, cuota_asign, o['r_mensual'])

                    # Fecha estimada de llegada
                    if estado_val == "En curso":
                        fecha_txt = fecha_estimada_llegada(plazo_orig)
                        desfase_txt = None
                    elif meses_reales:
                        fecha_txt = fecha_estimada_llegada(meses_reales)
                        desfase = meses_reales - plazo_orig
                        if desfase > 0:
                            desfase_txt = f"+{desfase} meses de retraso"
                        else:
                            desfase_txt = None
                    else:
                        fecha_txt = "—"
                        desfase_txt = "Sin asignación"

                    # Color del estado
                    if estado_val == "En curso":
                        estado_color, estado_icono = "#2ECC71", "✅"
                        estado_msg = "Cuota cubierta"
                    elif estado_val == "Parcial":
                        estado_color, estado_icono = "#F1C40F", "⚠️"
                        estado_msg = "Cuota parcial"
                    else:
                        estado_color, estado_icono = "#E74C3C", "⏳"
                        estado_msg = "Sin asignación"

                    # Diferencia cuota ideal vs asignada
                    diff = cuota_asign - cuota_ideal
                    diff_color = "#2ECC71" if diff >= 0 else "#E74C3C"
                    diff_txt = (f"+{fmt(diff, m_meta)}" if diff >= 0
                                else f"-{fmt(abs(diff), m_meta)}")

                    st.markdown(
                        f"""
<div style='background:#111;border-radius:10px;padding:12px 14px;margin:8px 0;'>

  <!-- Estado general -->
  <div style='display:flex;justify-content:space-between;align-items:center;
              border-bottom:1px solid #222;padding-bottom:8px;margin-bottom:10px;'>
    <span style='font-size:13px;font-weight:700;color:{estado_color};'>
      {estado_icono} {estado_msg}
    </span>
    <span style='font-size:11px;color:#888;'>
      Plazo original: {plazo_orig} meses
    </span>
  </div>

  <!-- Fila 1: Faltante total -->
  <div style='display:flex;justify-content:space-between;margin-bottom:6px;'>
    <span style='font-size:11px;color:#888;'>Faltante total (ajustado inflación)</span>
    <span style='font-size:12px;font-weight:700;color:#fff;'>{fmt(faltante, m_meta)}</span>
  </div>

  <!-- Fila 2: Cuota necesaria -->
  <div style='display:flex;justify-content:space-between;margin-bottom:6px;'>
    <span style='font-size:11px;color:#888;'>Cuota mensual necesaria</span>
    <span style='font-size:12px;font-weight:600;color:#aaa;'>{fmt(cuota_ideal, m_meta)}</span>
  </div>

  <!-- Fila 3: Cuota asignada (destacada) -->
  <div style='display:flex;justify-content:space-between;align-items:center;
              background:#1a1a2e;border-radius:6px;padding:6px 10px;margin-bottom:8px;'>
    <span style='font-size:11px;color:#aaa;font-weight:600;'>💰 Cuota asignada</span>
    <div style='text-align:right;'>
      <span style='font-size:15px;font-weight:800;color:{estado_color};'>{fmt(cuota_asign, m_meta)}</span>
      <span style='font-size:10px;color:{diff_color};margin-left:6px;'>({diff_txt})</span>
    </div>
  </div>

  <!-- Fila 4: Fecha estimada de llegada -->
  <div style='display:flex;justify-content:space-between;align-items:center;'>
    <span style='font-size:11px;color:#888;'>📅 Llegada estimada</span>
    <div style='text-align:right;'>
      <span style='font-size:13px;font-weight:700;color:#fff;'>{fecha_txt}</span>
      {"" if not desfase_txt else f"<br><span style='font-size:10px;color:#E74C3C;'>{desfase_txt}</span>"}
    </div>
  </div>

</div>
""",
                        unsafe_allow_html=True,
                    )

                    st.caption(
                        f"Costo futuro estimado: **{fmt(o['costo_futuro'], m_meta)}** "
                        f"(hoy {fmt(costo_total_val, m_meta)})"
                    )

                    instrumento = o['instrumento']
                    st.markdown(f"**{instrumento['emoji']} Estrategia:** {instrumento['tipo']}")
                    st.caption(instrumento['descripcion'])

                    # Advertencias contextuales
                    if instrumento.get("advertencias"):
                        for adv in instrumento["advertencias"]:
                            st.caption(adv)

                    # ── Tabs: Cartera · Glosario ──────────────────────────────
                    tab_proy, tab_cart, tab_glos = st.tabs(["📈 Proyección", "🥧 Cartera", "📖 Glosario"])

                    with tab_proy:
                        fig_proy = grafico_proyeccion(o, supuestos)
                        st.plotly_chart(fig_proy, use_container_width=True, key=f"proy_{idx}")

                    with tab_cart:
                        allocs = instrumento.get("allocations", [])
                        if allocs:
                            # Gráfico de torta
                            fig_pie = go.Figure(data=[go.Pie(
                                labels=[a["nombre"] for a in allocs],
                                values=[a["pct"] for a in allocs],
                                hole=0.45,
                                marker_colors=[a["color"] for a in allocs],
                                textinfo="percent",
                                hovertemplate="%{label}<br>%{value}%<extra></extra>",
                            )])
                            fig_pie.update_layout(
                                height=200,
                                margin=dict(t=4, b=4, l=4, r=4),
                                showlegend=False,
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)",
                            )
                            st.plotly_chart(fig_pie, use_container_width=True, key=f"pie_{idx}")
                            # Tabla detallada
                            for a in allocs:
                                st.markdown(
                                    f"<div style='display:flex;align-items:center;gap:8px;"
                                    f"border-left:3px solid {a['color']};padding:4px 8px;margin-bottom:4px;'>"
                                    f"<span style='font-weight:800;font-size:15px;color:{a['color']};min-width:36px;'>{a['pct']}%</span>"
                                    f"<div><div style='font-size:12px;font-weight:600;'>{a['nombre']}</div>"
                                    f"<div style='font-size:10px;color:#888;'>{a['clase']} · Riesgo: {a['riesgo']} · Liquidez: {a['liquidez']}</div></div>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )

                    with tab_glos:
                        allocs = instrumento.get("allocations", [])
                        if allocs:
                            for a in allocs:
                                if a.get("desc"):
                                    st.markdown(f"**{a['nombre']}**")
                                    st.caption(a["desc"])
                        else:
                            st.caption("Sin información adicional disponible.")

    st.divider()

    # ── Mejora 11: banner de cierre positivo ─────────────────────────────────
    metas_en_curso = sum(1 for o in objetivos_enriquecidos if o['estado'] == "En curso")
    total_metas = len(objetivos_enriquecidos)
    if total_metas > 0 and metas_en_curso == total_metas:
        st.success(
            f"🎉 **¡Ruta crítica completamente financiada!** "
            f"Todas tus {total_metas} metas están en curso. "
            f"Tu plan de ahorro cubre el 100% de tus objetivos al ritmo actual."
        )
    elif total_metas > 0:
        st.info(
            f"📊 **{metas_en_curso} de {total_metas} metas en curso.** "
            f"Revisá las metas en estado 'Parcial' o 'En espera' para ajustar tu ahorro."
        )

    st.header("⑤ Exportar Reporte")

    # Mejora 10: incluir fecha de generación en nombre del archivo
    from datetime import date as _date
    _fecha_hoy = _date.today().strftime("%Y-%m-%d")

    filas = tuple(
        (
            o["Meta"],
            o.get("Categoría", "Otro"),
            o["Prioridad"],
            o["moneda_meta"],
            round(float(o["Costo Total"]), 2),
            round(o["costo_futuro"], 2),
            round(float(o["Ya Ahorrado"]), 2),
            int(o["Plazo (Meses)"]),
            round(o['cuota_ideal_meta'], 2),
            round(o['cuota_asignada_meta'], 2),
            o['estado'],
            o['instrumento']["tipo"],
        )
        for o in objetivos_enriquecidos
    )

    perfil_data_export = (
        risk_score,
        perfil_label_show,
        objetivo_financiero,
        horizonte_perfil,
        int(conocimiento_score),
        st.session_state.score_tolerancia,
        st.session_state.score_capacidad,
        st.session_state.score_horizonte,
        st.session_state.score_conocimiento,
        st.session_state.score_objetivo,
    )

    st.download_button(
        label="📥 Exportar reporte a Excel",
        data=build_excel(filas, perfil_data=perfil_data_export),
        file_name=f"ruta_critica_financiera_{_fecha_hoy}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
