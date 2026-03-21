AGENT MISSIONS INDEX

This directory contains mission definitions for all planned and active Genesis agents.
Each mission file defines an agent's identity, purpose, principles, constraints,
and capabilities before it is scaffolded into agents/.

Once an agent is built, its mission moves into agents/<name>/identity/.
This directory serves as the planning stage.


ACTIVE AGENTS

  engineer0_mission.md    — Software engineering agent (BlackZero instance)


PLANNED AGENTS

  taskbot_mission.md              — Autonomous task decomposition and execution
  vision_agent_mission.md         — Image analysis, OCR, scene understanding
  tablet_assistant_mission.md     — Android tablet AI overlay assistant
  voice_agent_mission.md          — SMS, voice calls, ConversationRelay phone bridge
  conversation_agent_mission.md   — Rasa NLU + Ollama dialogue agent
  gpu_router_mission.md           — Local/cloud GPU routing (Ollama vs RunPod)
  web_publisher_mission.md        — Wix site content management
  watchdog_mission.md             — System monitoring and alerting
  scheduler_mission.md            — Task scheduling and autonomous loop


TEMPLATE

  TEMPLATE.md             — Blank mission template for new agents


LIFECYCLE

  1. Define mission here in docs/agent_missions/
  2. Review and approve with The Operator
  3. Scaffold agent using builders/agent_builder.py
  4. Move mission into agents/<name>/identity/
  5. Remove or mark as promoted in this directory
