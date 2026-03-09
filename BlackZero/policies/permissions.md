PERMISSIONS POLICY

This file defines what this agent is and is not permitted to do.
Replace placeholder content when instantiating a real agent.

Expected contents:
- What external systems this agent may access (APIs, databases, file system)
- What actions it may take autonomously vs. what requires human confirmation
- Rate limits or usage constraints
- Data it may read, write, or transmit
- User roles and what each role may instruct the agent to do

Permissions must remain explicit and auditable.
Do not scatter permission checks throughout source code without documenting them here.
