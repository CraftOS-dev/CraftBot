#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
View and analyze profiling data from the agent.

Usage:
    python scripts/view_profile.py                    # View latest profile
    python scripts/view_profile.py --list             # List all profile files
    python scripts/view_profile.py --file <filename>  # View specific profile
    python scripts/view_profile.py --compare          # Compare last 2 profiles
    python scripts/view_profile.py --summary          # Show brief summary
"""

import argparse
import json
import statistics
from pathlib import Path
from typing import Dict, List, Any


def get_profile_dir() -> Path:
    """Get the profile logs directory."""
    return Path("decorators/logs")


def list_profiles() -> List[Path]:
    """List all profile data files."""
    profile_dir = get_profile_dir()
    if not profile_dir.exists():
        return []
    return sorted(profile_dir.glob("profile_data_*.json"), reverse=True)


def load_profile(filepath: Path) -> Dict[str, Any]:
    """Load a profile data file."""
    return json.loads(filepath.read_text(encoding="utf-8"))


def format_duration(ms: float) -> str:
    """Format duration in human-readable form."""
    if ms >= 60000:
        return f"{ms / 60000:.1f}min"
    elif ms >= 1000:
        return f"{ms / 1000:.1f}s"
    else:
        return f"{ms:.1f}ms"


def print_summary(data: Dict[str, Any]) -> None:
    """Print a brief summary of the profile."""
    print("\n" + "=" * 60)
    print("PROFILING SUMMARY")
    print("=" * 60)
    print(f"Session ID: {data['session_id']}")
    print(f"Generated: {data['generated_at']}")
    print(f"Total Duration: {format_duration(data['total_duration_ms'])}")

    # Count operations
    total_ops = sum(s["count"] for s in data["operation_stats"].values())
    print(f"Total Operations: {total_ops}")
    print(f"Agent Loops: {len(data.get('loop_stats', []))}")

    # Top time consumers by category
    print("\nTime by Category:")
    print("-" * 60)
    category_stats = data.get("category_stats", {})
    sorted_cats = sorted(
        category_stats.items(), key=lambda x: x[1]["total_ms"], reverse=True
    )
    for cat, stats in sorted_cats[:5]:
        pct = (
            (stats["total_ms"] / data["total_duration_ms"] * 100)
            if data["total_duration_ms"] > 0
            else 0
        )
        print(f"  {cat:<20} {format_duration(stats['total_ms']):>10} ({pct:.1f}%)")

    # Loop stats
    loop_stats = data.get("loop_stats", [])
    if loop_stats:
        durations = [loop["duration_ms"] for loop in loop_stats]
        print("\nLoop Statistics:")
        print("-" * 60)
        print(f"  Average: {format_duration(statistics.mean(durations))}")
        print(f"  Min: {format_duration(min(durations))}")
        print(f"  Max: {format_duration(max(durations))}")
        if len(durations) > 1:
            print(f"  Std Dev: {format_duration(statistics.stdev(durations))}")


def print_full_report(data: Dict[str, Any]) -> None:
    """Print a full detailed report."""
    print("\n" + "=" * 80)
    print("AGENT PERFORMANCE PROFILING REPORT")
    print("=" * 80)
    print(f"Session ID: {data['session_id']}")
    print(f"Generated at: {data['generated_at']}")
    print(f"Total duration: {format_duration(data['total_duration_ms'])}")

    # Count total operations
    total_ops = sum(s["count"] for s in data["operation_stats"].values())
    print(f"Total operations recorded: {total_ops}")
    print(f"Agent loops completed: {len(data.get('loop_stats', []))}")
    print()

    # Category summary
    print("-" * 80)
    print("TIME BY CATEGORY")
    print("-" * 80)
    print(
        f"{'Category':<25} {'Count':>8} {'Total':>12} {'Avg':>10} {'Min':>10} {'Max':>10}"
    )
    print("-" * 80)

    category_stats = data.get("category_stats", {})
    for cat_name, stats in sorted(
        category_stats.items(), key=lambda x: x[1]["total_ms"], reverse=True
    ):
        print(
            f"{cat_name:<25} {stats['count']:>8} {format_duration(stats['total_ms']):>12} "
            f"{format_duration(stats['avg_ms']):>10} {format_duration(stats['min_ms']):>10} {format_duration(stats['max_ms']):>10}"
        )
    print()

    # Top slowest operations
    print("-" * 80)
    print("TOP 15 SLOWEST OPERATIONS (by average time)")
    print("-" * 80)
    print(f"{'Operation':<40} {'Category':<15} {'Count':>6} {'Avg':>10} {'Total':>12}")
    print("-" * 80)

    sorted_ops = sorted(
        data["operation_stats"].values(), key=lambda x: x["avg_ms"], reverse=True
    )
    for stat in sorted_ops[:15]:
        op_name = stat["name"][:38] + ".." if len(stat["name"]) > 40 else stat["name"]
        print(
            f"{op_name:<40} {stat['category']:<15} {stat['count']:>6} "
            f"{format_duration(stat['avg_ms']):>10} {format_duration(stat['total_ms']):>12}"
        )
    print()

    # Loop statistics
    loop_stats = data.get("loop_stats", [])
    if loop_stats:
        print("-" * 80)
        print("AGENT LOOP STATISTICS")
        print("-" * 80)

        durations = [loop["duration_ms"] for loop in loop_stats]
        print(f"Total loops: {len(loop_stats)}")
        print(f"Average loop duration: {format_duration(statistics.mean(durations))}")
        print(f"Min loop duration: {format_duration(min(durations))}")
        print(f"Max loop duration: {format_duration(max(durations))}")
        if len(durations) > 1:
            print(f"Std dev: {format_duration(statistics.stdev(durations))}")
        print()

        # Show individual loop breakdown
        print("Loop Breakdowns:")
        print("-" * 80)
        print(f"{'Loop #':<8} {'Duration':>12} {'Ops':>8} {'Breakdown'}")
        print("-" * 80)

        for loop in loop_stats[-10:]:
            breakdown = loop.get("breakdown_by_category", {})
            breakdown_str = ", ".join(
                f"{k}: {format_duration(v)}"
                for k, v in sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[
                    :4
                ]
            )
            print(
                f"{loop['loop_number']:<8} {format_duration(loop['duration_ms']):>12} "
                f"{loop['operation_count']:>8} {breakdown_str}"
            )
        print()

        # Check for performance degradation
        if len(durations) >= 5:
            first_half = durations[: len(durations) // 2]
            second_half = durations[len(durations) // 2 :]
            avg_first = statistics.mean(first_half)
            avg_second = statistics.mean(second_half)

            if avg_second > avg_first * 1.2:
                pct_slower = ((avg_second - avg_first) / avg_first) * 100
                print("WARNING: PERFORMANCE DEGRADATION DETECTED")
                print(f"  Later loops are {pct_slower:.1f}% slower than earlier loops")
                print(
                    f"  First half avg: {format_duration(avg_first)}, Second half avg: {format_duration(avg_second)}"
                )
                print()

    # All operations detail
    print("-" * 80)
    print("ALL OPERATIONS DETAIL")
    print("-" * 80)
    print(f"{'Operation':<45} {'Cat':<12} {'Count':>6} {'Avg':>8} {'Total':>10}")
    print("-" * 80)

    for stat in sorted(
        data["operation_stats"].values(), key=lambda x: x["total_ms"], reverse=True
    ):
        op_name = stat["name"][:43] + ".." if len(stat["name"]) > 45 else stat["name"]
        cat_short = (
            stat["category"][:10] + ".."
            if len(stat["category"]) > 12
            else stat["category"]
        )
        print(
            f"{op_name:<45} {cat_short:<12} {stat['count']:>6} "
            f"{format_duration(stat['avg_ms']):>8} {format_duration(stat['total_ms']):>10}"
        )

    print()
    print("=" * 80)
    print("END OF REPORT")
    print("=" * 80)


def compare_profiles(profile1: Dict[str, Any], profile2: Dict[str, Any]) -> None:
    """Compare two profiles side by side."""
    print("\n" + "=" * 80)
    print("PROFILE COMPARISON")
    print("=" * 80)
    print(f"Profile 1: {profile1['session_id']}")
    print(f"Profile 2: {profile2['session_id']}")
    print()

    # Compare totals
    print("-" * 80)
    print("OVERALL")
    print("-" * 80)
    print(f"{'Metric':<30} {'Profile 1':>15} {'Profile 2':>15} {'Diff':>15}")
    print("-" * 80)

    dur1, dur2 = profile1["total_duration_ms"], profile2["total_duration_ms"]
    diff_pct = ((dur2 - dur1) / dur1 * 100) if dur1 > 0 else 0
    diff_sign = "+" if diff_pct > 0 else ""
    print(
        f"{'Total Duration':<30} {format_duration(dur1):>15} {format_duration(dur2):>15} {diff_sign}{diff_pct:.1f}%"
    )

    loops1 = len(profile1.get("loop_stats", []))
    loops2 = len(profile2.get("loop_stats", []))
    print(f"{'Agent Loops':<30} {loops1:>15} {loops2:>15}")
    print()

    # Compare by category
    print("-" * 80)
    print("BY CATEGORY")
    print("-" * 80)
    print(f"{'Category':<25} {'P1 Avg':>12} {'P2 Avg':>12} {'Diff':>12}")
    print("-" * 80)

    all_cats = set(profile1.get("category_stats", {}).keys()) | set(
        profile2.get("category_stats", {}).keys()
    )
    for cat in sorted(all_cats):
        stat1 = profile1.get("category_stats", {}).get(cat, {})
        stat2 = profile2.get("category_stats", {}).get(cat, {})
        avg1 = stat1.get("avg_ms", 0)
        avg2 = stat2.get("avg_ms", 0)
        diff_pct = ((avg2 - avg1) / avg1 * 100) if avg1 > 0 else 0
        diff_sign = "+" if diff_pct > 0 else ""
        print(
            f"{cat:<25} {format_duration(avg1):>12} {format_duration(avg2):>12} {diff_sign}{diff_pct:.1f}%"
        )
    print()

    # Compare loop averages
    loop_stats1 = profile1.get("loop_stats", [])
    loop_stats2 = profile2.get("loop_stats", [])
    if loop_stats1 and loop_stats2:
        durations1 = [loop["duration_ms"] for loop in loop_stats1]
        durations2 = [loop["duration_ms"] for loop in loop_stats2]
        avg1 = statistics.mean(durations1)
        avg2 = statistics.mean(durations2)
        diff_pct = ((avg2 - avg1) / avg1 * 100) if avg1 > 0 else 0
        diff_sign = "+" if diff_pct > 0 else ""
        print("-" * 80)
        print("LOOP COMPARISON")
        print("-" * 80)
        print(f"{'Metric':<30} {'Profile 1':>15} {'Profile 2':>15} {'Diff':>15}")
        print("-" * 80)
        print(
            f"{'Avg Loop Duration':<30} {format_duration(avg1):>15} {format_duration(avg2):>15} {diff_sign}{diff_pct:.1f}%"
        )


def main():
    parser = argparse.ArgumentParser(description="View agent profiling data")
    parser.add_argument(
        "--list", "-l", action="store_true", help="List all profile files"
    )
    parser.add_argument("--file", "-f", type=str, help="View specific profile file")
    parser.add_argument(
        "--compare", "-c", action="store_true", help="Compare last 2 profiles"
    )
    parser.add_argument(
        "--summary", "-s", action="store_true", help="Show brief summary only"
    )

    args = parser.parse_args()

    profiles = list_profiles()

    if args.list:
        if not profiles:
            print("No profile files found in decorators/logs/")
            return
        print("\nAvailable profile files:")
        print("-" * 60)
        for p in profiles:
            try:
                data = load_profile(p)
                loops = len(data.get("loop_stats", []))
                print(f"  {p.name:<40} ({loops} loops)")
            except Exception:
                print(f"  {p.name:<40} (error reading)")
        return

    if args.compare:
        if len(profiles) < 2:
            print("Need at least 2 profiles to compare")
            return
        profile1 = load_profile(profiles[1])  # Older
        profile2 = load_profile(profiles[0])  # Newer
        compare_profiles(profile1, profile2)
        return

    # Load specific or latest profile
    if args.file:
        filepath = get_profile_dir() / args.file
        if not filepath.exists():
            print(f"Profile file not found: {filepath}")
            return
    else:
        if not profiles:
            print(
                "No profile files found. Run the agent with profiling enabled to generate data."
            )
            return
        filepath = profiles[0]

    data = load_profile(filepath)

    if args.summary:
        print_summary(data)
    else:
        print_full_report(data)


if __name__ == "__main__":
    main()
