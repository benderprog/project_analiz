from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.portaldb.gateway.factory import get_portal_gateway
from apps.portaldb.gateway.orm import ORMPortalGateway
from apps.portaldb.gateway.sql import SQLPortalGateway
from apps.portaldb.models import Event, Offender, Pu, Subdivision


class PortalGatewayFactoryTests(SimpleTestCase):
    @override_settings(PORTAL_GATEWAY_BACKEND="orm", PORTAL_DB_ALIAS="portal")
    def test_gateway_factory_selects_backend_orm(self):
        gateway = get_portal_gateway()
        self.assertIsInstance(gateway, ORMPortalGateway)

    @override_settings(PORTAL_GATEWAY_BACKEND="sql", PORTAL_DB_ALIAS="portal")
    def test_gateway_factory_selects_backend_sql(self):
        gateway = get_portal_gateway()
        self.assertIsInstance(gateway, SQLPortalGateway)


class ORMPortalGatewayTests(TestCase):
    databases = {"default", "portal"}

    @override_settings(PORTAL_DB_ALIAS="portal")
    def test_orm_gateway_shapes(self):
        pu = Pu.objects.using("portal").create(
            pu_id=uuid.uuid4(), full_name="Полное ПУ", short_name="ПУ"
        )
        subdivision = Subdivision.objects.using("portal").create(
            subdivision_id=uuid.uuid4(),
            name="Отдел 1",
            short_name="Отд-1",
            parent_pu=pu,
        )
        dt = timezone.make_aware(datetime(2026, 1, 1, 10, 0)) if timezone.is_naive(datetime.now()) else datetime(2026,1,1,10,0)
        event = Event.objects.using("portal").create(
            event_id=uuid.uuid4(),
            date_detection=dt,
            find_subdivision_unit=subdivision,
            event_type="Тип",
            article_of_law="12.1",
        )
        Offender.objects.using("portal").create(
            offender_id=uuid.uuid4(),
            event=event,
            second_name="Иванов",
            first_name="Иван",
            patronymic_name="Иванович",
            date_of_birth=date(1990, 1, 1),
        )

        gateway = ORMPortalGateway(alias="portal")

        pus = gateway.list_pus()
        self.assertEqual(pus[0].pu_id, pu.pu_id)
        subdivisions = gateway.list_subdivisions(pu_id=pu.pu_id)
        self.assertEqual(subdivisions[0].subdivision_id, subdivision.subdivision_id)
        events = gateway.search_events_by_subdivision_time(
            subdivision_id=subdivision.subdivision_id,
            dt_from=dt,
            dt_to=dt,
            limit=10,
        )
        self.assertEqual(events[0].event_id, event.event_id)
        offenders = gateway.get_offenders_by_event_ids([event.event_id])
        self.assertEqual(offenders[0].event_id, event.event_id)


class SQLPortalGatewayTests(SimpleTestCase):
    @patch("apps.portaldb.gateway.sql.get_sql_registry")
    @patch("apps.portaldb.gateway.sql.connections")
    def test_sql_gateway_executes_queries(self, mock_connections, mock_registry_factory):
        mock_registry = MagicMock()
        mock_registry.get_sql.return_value = "select 1"
        mock_registry_factory.return_value = mock_registry

        cursor_ctx = MagicMock()
        cursor = MagicMock()
        cursor.description = [
            ("event_id",),
            ("date_detection",),
            ("subdivision_id",),
            ("event_type",),
            ("article_of_law",),
        ]
        event_id = uuid.uuid4()
        subdivision_id = uuid.uuid4()
        cursor.fetchall.return_value = [
            (event_id, datetime(2026, 1, 1, 10, 0), subdivision_id, "Тип", "12.1")
        ]
        cursor_ctx.__enter__.return_value = cursor
        mock_connections.__getitem__.return_value.cursor.return_value = cursor_ctx

        gateway = SQLPortalGateway()
        rows = gateway.search_events_by_time(datetime(2026, 1, 1), datetime(2026, 1, 2), 10)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].event_id, event_id)
        self.assertEqual(cursor.execute.call_count, 2)
        first_call = cursor.execute.call_args_list[0].args[0]
        second_call_params = cursor.execute.call_args_list[1].args[1]
        self.assertIn("SET TIME ZONE", first_call)
        self.assertIn("from_ts", second_call_params)
        self.assertIn("to_ts", second_call_params)
