from __future__ import annotations

from datetime import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TORUM_SYMBOLS = ("XAUEUR", "XAUUSD")
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


class TorumV1Params(BaseModel):
    """Single source of truth for Torum V1 parameters.

    Extra keys are kept for backwards compatibility, but all known keys are
    normalized and validated before they reach the strategy engine.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    use_news: bool = True
    news_manual_policy: Literal["ALLOW", "WARN", "REQUIRE_ACCEPTANCE", "BLOCK"] = "WARN"

    timeframe: Literal["H2", "H3"] = "H2"
    unlock_timeframe_mode: Literal["BOTH", "H2", "H3"] = "BOTH"
    entry_timeframe: Literal["M5"] = "M5"
    session_start: str = "09:00"
    session_end: str = "15:00"
    session_days: list[str] = Field(default_factory=lambda: ["MO", "TU", "WE", "TH", "FR"])

    unlock_bullish_close_enabled: bool = True
    unlock_two_bearish_hold_low_enabled: bool = True
    unlock_min_body_pct: float = Field(0.0, ge=0.0, le=20.0)

    enable_operation_zones: bool = True
    require_zone: bool = True
    operation_zone_allow_confirmation_price_outside: bool = False
    operation_zone_price_tolerance_pct: float = Field(0.0, ge=0.0, le=10.0)
    operation_zone_time_tolerance_minutes: int = Field(0, ge=0, le=1440)

    pullback_enabled: bool = True
    pullback_max_count: int = Field(10, ge=1, le=100)
    pullback_min_pct: float = Field(0.0, ge=0.0, le=20.0)
    pullback_threshold_pct: float = Field(0.0, ge=0.0, le=20.0)
    pullback_entry_min_pct: float = Field(0.20, ge=0.0, le=20.0)
    pullback_lookback_bars: int = Field(12, ge=2, le=2000)
    pullback_swing_confirm_bars: int = Field(1, ge=0, le=50)
    pullback_allow_peak_extension: bool = True
    pullback_require_bearish_leg: bool = True
    pullback_min_bearish_candles: int = Field(1, ge=0, le=50)
    pullback_min_lower_close_candles: int = Field(1, ge=0, le=50)
    pullback_disallow_same_candle_peak_low: bool = True
    pullback_impulse_green_filter_enabled: bool = True
    pullback_recovery_pct: float = Field(0.10, ge=0.0, le=20.0)
    pullback_entry_recovery_pct: float = Field(0.0, ge=0.0, le=20.0)
    pullback_end_confirmation_bars: int = Field(1, ge=1, le=50)
    pullback_min_bars_between: int = Field(0, ge=0, le=500)
    pullback_use_wicks: bool = True
    pullback_use_close_confirmation: bool = True
    pullback_live_update_enabled: bool = True
    pullback_live_anchor_to_low: bool = True
    pullback_show_labels: bool = True
    pullback_show_only_live: bool = False
    pullback_label_decimals: int = Field(2, ge=0, le=6)
    pullback_line_width: int = Field(2, ge=1, le=8)
    pullback_opacity: float = Field(0.95, ge=0.1, le=1.0)
    show_pullback_debug: bool = False

    confirmation_bars: int = Field(1, ge=1, le=10)
    confirmation_require_bullish: bool = True
    confirmation_close_above_previous_high: bool = False
    confirmation_min_body_pct: float = Field(0.0, ge=0.0, le=100.0)
    confirmation_ignore_doji: bool = True

    one_position_per_symbol: bool = False
    max_equivalent_positions: int = Field(3, ge=1, le=10)
    support_s1_multiplier: int = Field(1, ge=1, le=3)
    support_s2_multiplier: int = Field(2, ge=1, le=3)
    support_s3_multiplier: int = Field(3, ge=1, le=3)
    support_max_distance_pct: float = Field(0.0, ge=0.0, le=10.0)
    support_reference: Literal["PULLBACK_LOW", "ENTRY_PRICE"] = "PULLBACK_LOW"
    support_degrade_enabled: bool = True

    ath_green_prefer_x2_entries: bool = True
    ath_red_limit_pct: float = Field(2.5, ge=0.0, le=100.0)
    ath_orange_limit_pct: float = Field(9.0, ge=0.0, le=100.0)
    ath_yellow_limit_pct: float = Field(15.0, ge=0.0, le=100.0)
    ath_green_limit_pct: float = Field(30.0, ge=0.0, le=100.0)
    risk_stress_drop_from_ath_pct: float = Field(30.0, ge=1.0, le=99.0)
    risk_max_balance_pct: float = Field(50.0, ge=1.0, le=100.0)
    risk_missing_snapshot_policy: Literal["BLOCK", "USE_LAST_VALID", "RECOMPUTE"] = "USE_LAST_VALID"

    usd_strength_filter_enabled: bool = True
    usd_strength_apply_to_symbols: list[str] = Field(default_factory=lambda: ["XAUUSD", "XAUEUR"])
    usd_strength_mode: Literal["only_operate_when_weak", "block_when_strong", "info_only"] = "only_operate_when_weak"
    usd_sma_period: int = Field(30, ge=2, le=500)
    usd_neutral_band_points: float = Field(0.10, ge=0.0, le=20.0)
    usd_allow_when_neutral: bool = False
    usd_strong_drop_override_enabled: bool = True
    usd_strong_drop_lookback_days: int = Field(3, ge=1, le=90)
    usd_strong_drop_min_pct: float = Field(0.45, ge=0.0, le=50.0)
    usd_strong_drop_require_bearish_close: bool = True
    usd_strength_strict: bool = False

    suggested_volume: float = Field(0.01, gt=0.0, le=1000.0)
    take_profit_percent: float = Field(0.09, gt=0.0, le=100.0)
    max_slippage_points: int = Field(20, ge=0, le=10000)
    tp_failure_policy: Literal["KEEP_OPEN_WARN", "RETRY", "CLOSE_POSITION"] = "RETRY"

    @field_validator("session_start", "session_end")
    @classmethod
    def validate_hhmm(cls, value: str) -> str:
        raw = value.strip()
        try:
            parsed = time.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("expected HH:MM") from exc
        return parsed.strftime("%H:%M")

    @field_validator("session_days")
    @classmethod
    def validate_days(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for day in value:
            item = str(day).strip().upper()
            if item not in WEEKDAYS:
                raise ValueError(f"invalid weekday: {day}")
            if item not in normalized:
                normalized.append(item)
        if not normalized:
            raise ValueError("at least one session day is required")
        return normalized

    @field_validator("usd_strength_apply_to_symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item).strip().upper() for item in value if str(item).strip()))

    @model_validator(mode="after")
    def validate_ranges(self) -> "TorumV1Params":
        if self.ath_red_limit_pct > self.ath_orange_limit_pct:
            raise ValueError("ATH red limit must be <= orange limit")
        if self.ath_orange_limit_pct > self.ath_yellow_limit_pct:
            raise ValueError("ATH orange limit must be <= yellow limit")
        if self.ath_yellow_limit_pct > self.ath_green_limit_pct:
            raise ValueError("ATH yellow limit must be <= green limit")
        if self.support_s1_multiplier > self.support_s2_multiplier:
            raise ValueError("S1 multiplier must be <= S2 multiplier")
        if self.support_s2_multiplier > self.support_s3_multiplier:
            raise ValueError("S2 multiplier must be <= S3 multiplier")
        self.pullback_threshold_pct = self.pullback_min_pct
        return self

    @classmethod
    def defaults_for_symbol(cls, symbol: str) -> "TorumV1Params":
        normalized = symbol.upper()
        values: dict[str, Any] = {}
        if normalized == "XAUUSD":
            values.update(session_start="15:30", session_end="21:00")
        else:
            values.update(session_start="09:00", session_end="15:00")
        return cls(**values)

    @classmethod
    def normalize(cls, symbol: str, raw: dict[str, Any] | None) -> "TorumV1Params":
        defaults = cls.defaults_for_symbol(symbol).model_dump()
        return cls.model_validate({**defaults, **(raw or {})})


class TorumFieldDescriptor(BaseModel):
    key: str
    label: str
    group: str
    type: Literal["boolean", "number", "select", "time", "multiselect", "text"]
    description: str
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: list[dict[str, str]] = Field(default_factory=list)
    advanced: bool = False
    per_symbol: bool = True


class TorumGroupDescriptor(BaseModel):
    key: str
    label: str
    description: str
    order: int


GROUPS = [
    TorumGroupDescriptor(key="market", label="Mercado y horario", description="Cuándo puede evaluarse la estrategia.", order=10),
    TorumGroupDescriptor(key="unlock", label="Desbloqueo", description="Condiciones previas para habilitar el activo.", order=20),
    TorumGroupDescriptor(key="pullback", label="Pullback", description="Cómo se detecta la corrección M5.", order=30),
    TorumGroupDescriptor(key="zone", label="Zona operativa", description="Dónde debe caer el mínimo del pullback.", order=40),
    TorumGroupDescriptor(key="confirmation", label="Confirmación", description="Qué vela confirma la entrada.", order=50),
    TorumGroupDescriptor(key="context", label="Noticias y dólar", description="Filtros de contexto externo.", order=60),
    TorumGroupDescriptor(key="support", label="Soportes", description="Agresividad S1, S2 y S3.", order=70),
    TorumGroupDescriptor(key="risk", label="Riesgo y ATH", description="Capacidad y escenario de estrés.", order=80),
    TorumGroupDescriptor(key="execution", label="Ejecución", description="Volumen, TP y comportamiento de orden.", order=90),
    TorumGroupDescriptor(key="visual", label="Visualización", description="Aspecto de los pullbacks en el gráfico.", order=100),
]


def _field(
    key: str,
    label: str,
    group: str,
    type_: Literal["boolean", "number", "select", "time", "multiselect", "text"],
    description: str,
    **kwargs: Any,
) -> TorumFieldDescriptor:
    return TorumFieldDescriptor(key=key, label=label, group=group, type=type_, description=description, **kwargs)


FIELDS = [
    _field("enabled", "Activo", "market", "boolean", "Activa este activo dentro de Torum V1."),
    _field("entry_timeframe", "Temporalidad de entrada", "market", "select", "Temporalidad en la que se evalúan pullback y confirmación.", options=[{"value": "M5", "label": "5 minutos"}], advanced=True),
    _field("session_start", "Inicio", "market", "time", "Hora de inicio en Europe/Madrid."),
    _field("session_end", "Fin", "market", "time", "Hora de fin en Europe/Madrid."),
    _field("session_days", "Días", "market", "multiselect", "Días en los que se permite evaluar.", options=[{"value": d, "label": l} for d, l in zip(WEEKDAYS, ("L", "M", "X", "J", "V", "S", "D"))]),

    _field("timeframe", "Desbloqueo preferido", "unlock", "select", "Temporalidad preferida para desbloquear.", options=[{"value": "H2", "label": "2 horas"}, {"value": "H3", "label": "3 horas"}]),
    _field("unlock_timeframe_mode", "Ventanas de desbloqueo", "unlock", "select", "Evalúa H2 y H3 o limita la regla a una sola temporalidad.", options=[{"value": "BOTH", "label": "H2 y H3"}, {"value": "H2", "label": "Solo H2"}, {"value": "H3", "label": "Solo H3"}]),
    _field("unlock_bullish_close_enabled", "Vela alcista", "unlock", "boolean", "Desbloquea con cierre alcista."),
    _field("unlock_two_bearish_hold_low_enabled", "Dos bajistas sin perder mínimo", "unlock", "boolean", "Desbloquea cuando dos velas bajistas mantienen el mínimo."),
    _field("unlock_min_body_pct", "Cuerpo mínimo", "unlock", "number", "Cuerpo mínimo de la vela de desbloqueo respecto a su precio.", unit="%", minimum=0, maximum=20, step=0.01, advanced=True),

    _field("pullback_enabled", "Detección activada", "pullback", "boolean", "Activa el detector de pullbacks usado por el bot."),
    _field("pullback_entry_min_pct", "Pullback mínimo de entrada", "pullback", "number", "Caída mínima requerida para una señal automática.", unit="%", minimum=0, maximum=20, step=0.01),
    _field("pullback_min_pct", "Umbral visual", "pullback", "number", "Caída mínima usada para mostrar pullbacks; puede ser menor que la entrada.", unit="%", minimum=0, maximum=20, step=0.01),
    _field("pullback_max_count", "Máximo mostrado", "pullback", "number", "Cantidad máxima de pullbacks recientes conservados.", unit="pullbacks", minimum=1, maximum=100, step=1),
    _field("pullback_lookback_bars", "Lookback", "pullback", "number", "Velas M5 analizadas.", unit="velas", minimum=2, maximum=2000, step=1),
    _field("pullback_use_wicks", "Usar mechas", "pullback", "boolean", "Usa máximos y mínimos, no solo cierres."),
    _field("pullback_require_bearish_leg", "Exigir tramo bajista", "pullback", "boolean", "Evita falsos pullbacks en velas verdes de rango amplio."),
    _field("pullback_min_bearish_candles", "Velas bajistas mínimas", "pullback", "number", "Cantidad mínima de velas rojas.", minimum=0, maximum=50, step=1, advanced=True),
    _field("pullback_min_lower_close_candles", "Cierres descendentes mínimos", "pullback", "number", "Cantidad mínima de cierres inferiores al cierre anterior.", minimum=0, maximum=50, step=1, advanced=True),
    _field("pullback_recovery_pct", "Recuperación visual", "pullback", "number", "Rebote usado para cerrar y separar los pullbacks mostrados en el gráfico.", unit="%", minimum=0, maximum=20, step=0.01, advanced=True),
    _field("pullback_entry_recovery_pct", "Rebote mínimo para entrar", "pullback", "number", "Rebote adicional exigido a la vela alcista después de alcanzar el pullback mínimo. Déjalo en 0 para confirmar con la primera vela alcista o doji válida.", unit="%", minimum=0, maximum=20, step=0.01, advanced=True),
    _field("pullback_end_confirmation_bars", "Velas para cerrar PB", "pullback", "number", "Número de velas que confirman que el pullback terminó.", minimum=1, maximum=50, step=1, advanced=True),
    _field("pullback_min_bars_between", "Separación mínima", "pullback", "number", "Velas mínimas entre dos pullbacks cerrados.", unit="velas", minimum=0, maximum=500, step=1, advanced=True),
    _field("pullback_swing_confirm_bars", "Confirmar máximo", "pullback", "number", "Velas que confirman el máximo de origen.", minimum=0, maximum=50, step=1, advanced=True),
    _field("pullback_allow_peak_extension", "Actualizar máximo", "pullback", "boolean", "Mueve el origen a un máximo posterior más alto sin perder un pullback válido.", advanced=True),
    _field("pullback_disallow_same_candle_peak_low", "Separar máximo y mínimo", "pullback", "boolean", "Impide formar un pullback con el máximo y mínimo de una sola vela.", advanced=True),
    _field("pullback_impulse_green_filter_enabled", "Filtrar impulso verde", "pullback", "boolean", "Evita marcar velas alcistas amplias como pullback sin tramo bajista.", advanced=True),
    _field("pullback_use_close_confirmation", "Confirmar con cierre", "pullback", "boolean", "Exige confirmación por cierre y no solo por mecha.", advanced=True),
    _field("pullback_live_update_enabled", "Actualizar PB vivo", "pullback", "boolean", "Actualiza el pullback actual con el precio vivo.", advanced=True),
    _field("pullback_live_anchor_to_low", "Anclar al mínimo", "pullback", "boolean", "Mantiene el extremo del pullback vivo en el mínimo alcanzado.", advanced=True),

    _field("enable_operation_zones", "Usar zonas Torum", "zone", "boolean", "Permite que la estrategia lea rectángulos marcados como zona operativa."),
    _field("require_zone", "Requerir rectángulo", "zone", "boolean", "El mínimo debe estar dentro de una zona Torum."),
    _field(
        "operation_zone_allow_confirmation_price_outside",
        "Permitir entrada si la vela alcista sale de la zona",
        "zone",
        "boolean",
        "Solo si el mínimo del pullback y la confirmación temporal estuvieron dentro del rectángulo: permite que la vela alcista y la entrada salgan por precio.",
    ),
    _field("operation_zone_price_tolerance_pct", "Tolerancia de precio", "zone", "number", "Margen adicional alrededor de la zona.", unit="%", minimum=0, maximum=10, step=0.01, advanced=True),
    _field("operation_zone_time_tolerance_minutes", "Tolerancia temporal", "zone", "number", "Margen antes y después de los límites temporales del rectángulo.", unit="min", minimum=0, maximum=1440, step=1, advanced=True),

    _field("confirmation_bars", "Velas de confirmación", "confirmation", "number", "Velas alcistas o doji cerradas necesarias para confirmar. La propia vela que marca el mínimo puede contar como la primera.", minimum=1, maximum=10, step=1),
    _field("confirmation_require_bullish", "Exigir vela alcista", "confirmation", "boolean", "El cierre debe quedar por encima de la apertura."),
    _field("confirmation_close_above_previous_high", "Cerrar sobre máximo anterior", "confirmation", "boolean", "Confirmación más estricta.", advanced=True),
    _field("confirmation_min_body_pct", "Cuerpo mínimo", "confirmation", "number", "Cuerpo mínimo de la vela de confirmación respecto al precio.", unit="%", minimum=0, maximum=100, step=0.01, advanced=True),
    _field(
        "confirmation_ignore_doji",
        "Contar doji como vela alcista",
        "confirmation",
        "boolean",
        "Permite que una vela con apertura y cierre iguales confirme el final del pullback y la entrada.",
        advanced=True,
    ),

    _field("use_news", "Usar filtro de noticias", "context", "boolean", "Aplica las reglas configuradas en Noticias."),
    _field("news_manual_policy", "Compras manuales", "context", "select", "Qué hacer con una compra manual durante noticias.", options=[{"value": "ALLOW", "label": "Permitir"}, {"value": "WARN", "label": "Avisar"}, {"value": "REQUIRE_ACCEPTANCE", "label": "Exigir aceptación"}, {"value": "BLOCK", "label": "Bloquear"}]),
    _field("usd_strength_filter_enabled", "Filtro DXY", "context", "boolean", "El bot solo opera si el estado del dólar lo permite."),
    _field("usd_strength_apply_to_symbols", "Aplicar DXY a", "context", "multiselect", "Activos sometidos al filtro de fortaleza del dólar.", options=[{"value": symbol, "label": symbol} for symbol in TORUM_SYMBOLS], advanced=True),
    _field("usd_strength_mode", "Política DXY", "context", "select", "Cómo afecta el estado del dólar.", options=[{"value": "only_operate_when_weak", "label": "Solo dólar débil"}, {"value": "block_when_strong", "label": "Bloquear solo fuerte"}, {"value": "info_only", "label": "Solo informar"}]),
    _field("usd_sma_period", "SMA DXY", "context", "number", "Periodo diario de la media.", minimum=2, maximum=500, step=1),
    _field("usd_neutral_band_points", "Banda neutra", "context", "number", "Distancia alrededor de la SMA considerada neutral.", unit="puntos DXY", minimum=0, maximum=20, step=0.01, advanced=True),
    _field("usd_allow_when_neutral", "Permitir neutro", "context", "boolean", "Permite operar cerca de la SMA."),
    _field("usd_strong_drop_override_enabled", "Permitir caída fuerte", "context", "boolean", "Considera débil al dólar si cae con fuerza sobre la SMA."),
    _field("usd_strong_drop_lookback_days", "Ventana de caída", "context", "number", "Días usados para medir una bajada fuerte del dólar.", unit="días", minimum=1, maximum=90, step=1, advanced=True),
    _field("usd_strong_drop_min_pct", "Caída fuerte mínima", "context", "number", "Caída necesaria para activar el override.", unit="%", minimum=0, maximum=50, step=0.01),
    _field("usd_strong_drop_require_bearish_close", "Exigir vela DXY bajista", "context", "boolean", "El override requiere que la última vela diaria cierre bajista.", advanced=True),
    _field("usd_strength_strict", "Bloquear si no hay DXY", "context", "boolean", "Impide entradas si el snapshot DXY no está disponible.", advanced=True),

    _field("one_position_per_symbol", "Una posición por activo", "support", "boolean", "Impide una segunda entrada aunque el resto de límites la permitiera.", advanced=True),
    _field("support_s1_multiplier", "S1", "support", "number", "Entradas equivalentes en soporte S1.", minimum=1, maximum=3, step=1),
    _field("support_s2_multiplier", "S2", "support", "number", "Entradas equivalentes en soporte S2.", minimum=1, maximum=3, step=1),
    _field("support_s3_multiplier", "S3", "support", "number", "Entradas equivalentes en soporte S3.", minimum=1, maximum=3, step=1),
    _field("support_max_distance_pct", "Distancia máxima", "support", "number", "Distancia máxima al soporte para aplicar su multiplicador.", unit="%", minimum=0, maximum=10, step=0.01, advanced=True),
    _field("support_reference", "Referencia del soporte", "support", "select", "Precio usado para decidir proximidad al soporte.", options=[{"value": "PULLBACK_LOW", "label": "Mínimo del pullback"}, {"value": "ENTRY_PRICE", "label": "Precio de entrada"}], advanced=True),
    _field("support_degrade_enabled", "Reducir si no cabe", "support", "boolean", "Degrada triple a doble o simple por riesgo."),

    _field("max_equivalent_positions", "Máximo equivalente", "risk", "number", "Capacidad máxima total.", minimum=1, maximum=10, step=1),
    _field("ath_red_limit_pct", "Límite rojo", "risk", "number", "Distancia al ATH en la que se bloquea la operativa.", unit="%", minimum=0, maximum=100, step=0.1),
    _field("ath_orange_limit_pct", "Límite naranja", "risk", "number", "Fin de la zona de una entrada equivalente.", unit="%", minimum=0, maximum=100, step=0.1),
    _field("ath_yellow_limit_pct", "Límite amarillo", "risk", "number", "Fin de la zona de dos entradas equivalentes.", unit="%", minimum=0, maximum=100, step=0.1),
    _field("ath_green_limit_pct", "Límite verde", "risk", "number", "Fin de la zona de tres entradas equivalentes.", unit="%", minimum=0, maximum=100, step=0.1),
    _field("ath_green_prefer_x2_entries", "Preferir doble en verde", "risk", "boolean", "En zona verde intenta agrupar dos equivalentes cuando sea posible.", advanced=True),
    _field("risk_stress_drop_from_ath_pct", "Caída de estrés desde ATH", "risk", "number", "Escenario adverso usado para el cálculo.", unit="%", minimum=1, maximum=99, step=0.1),
    _field("risk_max_balance_pct", "Riesgo máximo", "risk", "number", "Pérdida potencial máxima sobre el balance.", unit="% balance", minimum=1, maximum=100, step=0.1),
    _field("risk_missing_snapshot_policy", "Si falta snapshot", "risk", "select", "Comportamiento si el riesgo no está precalculado.", options=[{"value": "BLOCK", "label": "Bloquear"}, {"value": "USE_LAST_VALID", "label": "Usar último válido"}, {"value": "RECOMPUTE", "label": "Recalcular"}], advanced=True),

    _field("suggested_volume", "Lotaje base", "execution", "number", "Volumen de una entrada simple.", unit="lotes", minimum=0.01, maximum=1000, step=0.01),
    _field("take_profit_percent", "Take profit", "execution", "number", "TP desde el precio real ejecutado.", unit="%", minimum=0.001, maximum=100, step=0.001),
    _field("max_slippage_points", "Desviación máxima", "execution", "number", "Desviación permitida en MT5.", unit="puntos", minimum=0, maximum=10000, step=1, advanced=True),
    _field("tp_failure_policy", "Si falla el TP", "execution", "select", "Acción si MT5 no acepta el TP tras abrir.", options=[{"value": "KEEP_OPEN_WARN", "label": "Mantener y avisar"}, {"value": "RETRY", "label": "Reintentar"}, {"value": "CLOSE_POSITION", "label": "Cerrar posición"}], advanced=True),

    _field("show_pullback_debug", "Mostrar pullbacks", "visual", "boolean", "Preferencia visual del gráfico."),
    _field("pullback_show_labels", "Etiquetas", "visual", "boolean", "Muestra el porcentaje."),
    _field("pullback_show_only_live", "Solo PB vivo", "visual", "boolean", "Oculta los pullbacks cerrados y muestra únicamente el actual.", advanced=True),
    _field("pullback_label_decimals", "Decimales", "visual", "number", "Decimales de la etiqueta del porcentaje.", minimum=0, maximum=6, step=1, advanced=True),
    _field("pullback_line_width", "Ancho", "visual", "number", "Grosor de línea.", minimum=1, maximum=8, step=1),
    _field("pullback_opacity", "Opacidad", "visual", "number", "Opacidad de la línea.", minimum=0.1, maximum=1, step=0.05),
]



def ui_schema() -> dict[str, Any]:
    return {
        "groups": [item.model_dump() for item in GROUPS],
        "fields": [item.model_dump() for item in FIELDS],
        "hidden_fields": ["pullback_threshold_pct"],
        "defaults": {symbol: TorumV1Params.defaults_for_symbol(symbol).model_dump() for symbol in TORUM_SYMBOLS},
    }
