/**
 * What is stopping Seshat from working, and the command that fixes it.
 *
 * An empty cockpit looks identical whether the project is new or the model
 * was never installed — and journaling fails silently by design, because
 * capture must keep running when inference cannot. This banner is what turns
 * that silence into something a user can act on without going to the README.
 */
import type { SetupStatus } from "./api";

function Fix({ what, command }: { what: string; command: string }) {
  return (
    <li>
      {what} <code className="md-code">{command}</code>
    </li>
  );
}

export function Health({ setup }: { setup: SetupStatus }) {
  const fixes = [];

  if (!setup.ollama_installed) {
    fixes.push(
      <li key="install">
        Install Ollama from <span className="mono">https://ollama.com/download</span>
      </li>,
    );
  } else if (!setup.ollama_running) {
    fixes.push(
      <Fix key="run" what="Start Ollama, then:" command="seshat setup" />,
    );
  }

  for (const model of setup.missing_models) {
    // Only actionable once Ollama can actually answer a pull.
    if (setup.ollama_running) {
      fixes.push(<Fix key={model} what="Pull the model:" command={`ollama pull ${model}`} />);
    }
  }

  return (
    <div className="health" role="status">
      <div className="health-head">
        Capture is running, but journaling and search are not.
      </div>
      <ul className="health-fixes">{fixes}</ul>
      <div className="health-foot">
        Your work is still being recorded — raw events are captured either way,
        and entries are generated once this is fixed.
      </div>
    </div>
  );
}
