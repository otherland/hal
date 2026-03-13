HAL — Harmful Action Limiter
"I'm sorry, I can't let you do that."


HAL 9000 couldn't be overridden. We considered that a design goal.


Turning off autopilot isn't an option anymore.
Agents are writing your code, running your tests, managing your infra — and that's not slowing down, it's accelerating. Every major IDE now ships an agent mode. Every serious team is adopting one.
The commands these agents run are correct 99% of the time, which is exactly what makes the 1% so dangerous — you stop watching.
You're not reviewing every rm, every git reset, every terraform apply across 40 parallel sessions. Nobody is.
And the agent that nukes your working directory isn't malicious — it's just confidently wrong about one flag, one path, one assumption.
A single git push --force on the wrong branch doesn't care whether you meant to enable autopilot or not.
This isn't a settings problem. It's a missing layer.
HAL sits between the agent and your shell, catches the 1%, and costs you less than a millisecond on every other command.

