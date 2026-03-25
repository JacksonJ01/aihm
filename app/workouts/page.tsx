import WorkoutsSession from "./workoutsSession";

export default function Page() {
  return (
    <div style={{ padding: 20 }}>
      <main>
        <h1>Workouts</h1>
        <WorkoutsSession />
      </main>
    </div>
  );
}