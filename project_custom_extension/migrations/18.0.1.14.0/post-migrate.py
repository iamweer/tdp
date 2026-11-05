from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Tarea 2595: festivos de Colombia como ausencias globales del horario.
    env["resource.calendar"]._tdp_sync_colombia_holidays()
