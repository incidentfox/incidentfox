# Copyright 2026 IncidentFox, Inc.
#
# Licensed under the Business Source License 1.1 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://github.com/incidentfox/incidentfox/blob/main/LICENSE-ENTERPRISE
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
AI Learning Pipeline - Self-Learning System for IncidentFox.

This package implements the scheduled learning pipeline that:
1. Ingests knowledge from configured sources (Confluence, GitHub, etc.)
2. Processes pending knowledge teachings from agents
3. Runs maintenance tasks (decay, rebalancing, gap detection)
4. Generates improvement proposals for human review
"""

__version__ = "1.0.0"
