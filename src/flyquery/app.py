# Copyright 2024-2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""PyFly application entry point for flyquery.

``scan_packages`` declares every package containing ``@configuration``,
``@rest_controller``, ``@service``, ``@command_handler``,
``@query_handler``, or ``@repository`` beans so pyfly's DI container
can discover them at boot.

Exception handlers are registered explicitly via
``flyquery.web.conventions.register_exception_handlers(app)`` in
``flyquery.main`` -- pyfly's FastAPI adapter does not scan
``@controller_advice`` beans, so the conventions handler table is
hand-wired against the FastAPI app.
"""

from __future__ import annotations

from pyfly.core import pyfly_application
from pyfly.starters.core import enable_core_stack

from flyquery import __version__


@enable_core_stack
@pyfly_application(
    name="flyquery",
    version=__version__,
    description=(
        "flyquery -- Operational Structured-Data Intelligence "
        "(upload-driven). Multi-tenant ingestion + Text-to-SQL "
        "over user-uploaded structured files. Part of Firefly "
        "Framework."
    ),
    scan_packages=[
        "flyquery.core",  # @configuration class
        "flyquery.core.services",  # CQRS handlers + @service beans
        # @service beans for the EDA publisher wrapper. Without this,
        # ``IngestPublisher`` is invisible to DI and the IngestService
        # ends up with ``event_publisher=None`` -- every publish call
        # silently falls into the in-memory branch and the worker
        # never sees the IngestRequested event.
        "flyquery.core.eda",
        # CallbackWorker + CallbackOutboxRepository. Without this the
        # callback path falls back to "no bean" and the worker can't
        # enqueue terminal-state webhooks.
        "flyquery.core.services.callbacks",
        "flyquery.web.controllers",  # REST controllers (user-tier)
        "flyquery.web.controllers.agent",  # REST controllers (agent-tier)
    ],
)
class FlyqueryApplication:
    """Marker class consumed by :class:`PyFlyApplication` at boot."""
