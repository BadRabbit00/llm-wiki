import { useAll } from "../api";
import { useAuth } from "../auth";

interface Person {
  person: string;
  display_name: string;
  updated_at: string;
}

export function PersonName({
  identity,
  fallback,
}: {
  identity: string;
  fallback?: string;
}) {
  const { actor } = useAuth();
  const people = useAll<Person>(
    "/people",
    !!actor && actor.clearance !== "public",
  );
  const name = people.data?.find(
    (person) => person.person === identity,
  )?.display_name;
  return <span title={identity}>{name || fallback || identity}</span>;
}
