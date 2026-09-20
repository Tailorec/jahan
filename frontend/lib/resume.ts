/* When a resume can be forced. The engine refuses a resume whose inputs moved since the run began, and says
   which input moved and from what to what; only that refusal is worth forcing past. A run that died for any
   other reason is resumed the ordinary way, and forcing it would change nothing. */

export function movedInputRefusal(text: string | null | undefined): string | null {
  const found = /resume refused: (.+)/.exec(text ?? "");
  return found ? found[1].trim() : null;
}

export const FORCE_WARNING =
  "Forcing a resume continues this run with inputs that have changed since it began. " +
  "The run records what it was forced past, and every view of it says so. " +
  "Do this only if the change is one you meant to make. Continue?";
