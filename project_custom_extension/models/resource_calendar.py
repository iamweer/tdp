from datetime import date, datetime, time, timedelta

import logging

import pytz
from dateutil.easter import easter

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

HOLIDAY_TIMEZONE = "America/Bogota"
HOLIDAY_NAME_PREFIX = "Festivo: "

# (mes, día, nombre) de los festivos que no se trasladan.
_FIXED_HOLIDAYS = (
    (1, 1, "Año Nuevo"),
    (5, 1, "Día del Trabajo"),
    (7, 20, "Día de la Independencia"),
    (8, 7, "Batalla de Boyacá"),
    (12, 8, "Inmaculada Concepción"),
    (12, 25, "Navidad"),
)

# Ley Emiliani (Ley 51 de 1983): se trasladan al lunes siguiente.
_MOVABLE_HOLIDAYS = (
    (1, 6, "Reyes Magos"),
    (3, 19, "San José"),
    (6, 29, "San Pedro y San Pablo"),
    (8, 15, "Asunción de la Virgen"),
    (10, 12, "Día de la Raza"),
    (11, 1, "Todos los Santos"),
    (11, 11, "Independencia de Cartagena"),
)

# (días desde el domingo de Pascua, nombre, se traslada al lunes).
_EASTER_HOLIDAYS = (
    (-3, "Jueves Santo", False),
    (-2, "Viernes Santo", False),
    (39, "Ascensión del Señor", True),
    (60, "Corpus Christi", True),
    (68, "Sagrado Corazón", True),
)


def _next_monday(day):
    return day + timedelta(days=(7 - day.weekday()) % 7)


def colombia_public_holidays(year):
    """Festivos de Colombia del año: lista ordenada de ``(fecha, nombre)``."""
    holidays = [(date(year, month, day), name) for month, day, name in _FIXED_HOLIDAYS]
    holidays += [
        (_next_monday(date(year, month, day)), name)
        for month, day, name in _MOVABLE_HOLIDAYS
    ]
    easter_sunday = easter(year)
    for offset, name, movable in _EASTER_HOLIDAYS:
        day = easter_sunday + timedelta(days=offset)
        holidays.append((_next_monday(day) if movable else day, name))
    return sorted(holidays)


class ResourceCalendar(models.Model):
    _inherit = "resource.calendar"

    def _tdp_weekday_hours(self, weekday):
        """Horas laborables del calendario en un día de la semana (0 = lunes)."""
        self.ensure_one()
        return sum(
            attendance.hour_to - attendance.hour_from
            for attendance in self.attendance_ids
            if int(attendance.dayofweek) == weekday
            and attendance.day_period != "lunch"
            and not attendance.display_type
            and not attendance.resource_id
        )

    def _tdp_holidays(self, date_from, date_to):
        """Festivos (ausencias globales) del calendario entre dos fechas.

        Devuelve ``{fecha: nombre}`` en la zona horaria del calendario.
        """
        self.ensure_one()
        timezone = pytz.timezone(self.tz or HOLIDAY_TIMEZONE)
        start = timezone.localize(datetime.combine(date_from, time.min))
        end = timezone.localize(datetime.combine(date_to, time.max))
        leaves = self.env["resource.calendar.leaves"].sudo().search([
            ("resource_id", "=", False),
            ("calendar_id", "in", [False, self.id]),
            ("company_id", "in", [False, self.company_id.id]),
            ("date_from", "<=", end.astimezone(pytz.utc).replace(tzinfo=None)),
            ("date_to", ">=", start.astimezone(pytz.utc).replace(tzinfo=None)),
        ])
        holidays = {}
        for leave in leaves:
            local_from = pytz.utc.localize(leave.date_from).astimezone(timezone).date()
            local_to = pytz.utc.localize(leave.date_to).astimezone(timezone).date()
            day = max(local_from, date_from)
            while day <= min(local_to, date_to):
                name = leave.name or ""
                if name.startswith(HOLIDAY_NAME_PREFIX):
                    name = name[len(HOLIDAY_NAME_PREFIX):]
                holidays.setdefault(day, name or "Festivo")
                day += timedelta(days=1)
        return holidays

    @api.model
    def _tdp_sync_colombia_holidays(self, years=None):
        """Crea los festivos de Colombia como ausencias globales.

        Una ausencia de día completo por festivo en cada calendario laboral.
        Es idempotente: no duplica un día que ya tenga una ausencia global,
        así se respetan las ediciones o eliminaciones manuales de ese año.
        """
        Leave = self.env["resource.calendar.leaves"].sudo()
        if years is None:
            today = fields.Date.context_today(self.with_context(tz=HOLIDAY_TIMEZONE))
            years = (today.year, today.year + 1)
        created = 0
        for calendar in self.sudo().search([]):
            timezone = pytz.timezone(calendar.tz or HOLIDAY_TIMEZONE)
            for year in years:
                # A year already loaded (even partially edited) is left alone.
                existing = calendar._tdp_holidays(date(year, 1, 1), date(year, 12, 31))
                if existing:
                    continue
                values = []
                for day, name in colombia_public_holidays(year):
                    start = timezone.localize(datetime.combine(day, time.min))
                    end = timezone.localize(datetime.combine(day, time(23, 59, 59)))
                    values.append({
                        "name": f"{HOLIDAY_NAME_PREFIX}{name}",
                        "calendar_id": calendar.id,
                        "company_id": calendar.company_id.id,
                        "resource_id": False,
                        "time_type": "leave",
                        "date_from": start.astimezone(pytz.utc).replace(tzinfo=None),
                        "date_to": end.astimezone(pytz.utc).replace(tzinfo=None),
                    })
                Leave.create(values)
                created += len(values)
        if created:
            _logger.info("Festivos de Colombia creados: %s ausencias globales.", created)
        return created

    @api.model
    def _cron_sync_colombia_holidays(self):
        return self._tdp_sync_colombia_holidays()
