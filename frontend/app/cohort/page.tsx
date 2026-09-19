import { redirect } from "next/navigation";

/* The glossary calls it a population, never a cohort — this address keeps old links working. */
export default async function CohortRedirect({
  searchParams,
}: {
  searchParams: Promise<{ run?: string }>;
}) {
  const { run } = await searchParams;
  redirect(run ? `/population?run=${run}` : "/population");
}
