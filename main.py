from webwork import WeBWorKManager


def main():
    manager = WeBWorKManager()

    for class_name in manager.get_classes():
        print(f"\n{'=' * 60}")
        print(f"  {class_name}")
        print(f"{'=' * 60}")

        client = manager.client(class_name)
        if not client.login():
            print("  ✗ Login failed.")
            continue
        print("  ✓ Logged in.\n")

        # List all sets with due dates
        due_dates = manager.get_due_dates(class_name)
        print(f"  Found {len(due_dates)} homework set(s):\n")
        for i, d in enumerate(due_dates, 1):
            print(f"  {i:>2}. {d['name']}")
            print(f"      Due: {d['due_date']}")
            print(f"      Status: {d['status']}")
            print()

        # For each open set, show progress
        open_sets = manager.get_open_sets(class_name)
        for hw in open_sets:
            print(f"  --- {hw.name} (due {hw.due_date}) ---\n")
            info = manager.get_set_info(class_name, hw.name)
            if info is None or not info.problems:
                print("    No problems found.\n")
                continue

            for p in info.problems:
                marker = "✓" if p.status == "100%" else "○"
                print(
                    f"    {marker} {p.name:<14} | "
                    f"Attempts: {p.attempts:<4} | "
                    f"Remaining: {p.remaining:<10} | "
                    f"Worth: {p.worth} | "
                    f"Status: {p.status}"
                )

            total = sum(p.worth for p in info.problems)
            completed = sum(p.worth for p in info.problems if p.status == "100%")
            print(f"\n    Progress: {completed}/{total} points\n")

        # Show first problem of first open set as a demo
        if open_sets:
            demo_set = open_sets[0]
            print(f"  --- Demo: fetching Problem 1 from {demo_set.name} ---\n")
            problem = manager.get_problem(class_name, demo_set.name, 1)
            if problem:
                print(f"    LaTeX body:\n")
                for line in problem.body_latex.splitlines():
                    if line.strip():
                        print(f"      {line}")
                print()
                print(f"    Answer fields:")
                for af in problem.answer_fields:
                    print(
                        f"      - {af['name']} (type={af['type']}, label={af['label']})"
                    )
                print(
                    f"\n    Attempts: {problem.attempts}, Remaining: {problem.remaining}"
                )
            else:
                print("    Could not load problem.\n")


if __name__ == "__main__":
    main()
