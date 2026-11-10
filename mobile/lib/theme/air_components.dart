import 'package:flutter/material.dart';

import 'air_theme.dart';

enum AirStatusTone { neutral, positive, negative, warning }

/// Standard AIR surface used for dashboard sections and feature panels.
class AirPanel extends StatelessWidget {
  const AirPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(AirSpacing.md),
    this.onTap,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final content = Padding(padding: padding, child: child);
    if (onTap == null) return Card(child: content);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(onTap: onTap, child: content),
    );
  }
}

/// Consistent compact metric tile. Values should come from verified app data.
class AirMetricCard extends StatelessWidget {
  const AirMetricCard({
    super.key,
    required this.label,
    required this.value,
    this.caption,
    this.tone = AirStatusTone.neutral,
  });

  final String label;
  final String value;
  final String? caption;
  final AirStatusTone tone;

  Color _toneColor(ColorScheme scheme) {
    switch (tone) {
      case AirStatusTone.positive:
        return AirPalette.positive;
      case AirStatusTone.negative:
        return AirPalette.negative;
      case AirStatusTone.warning:
        return AirPalette.warning;
      case AirStatusTone.neutral:
        return scheme.onSurface;
    }
  }

  @override
  Widget build(BuildContext context) {
    final color = _toneColor(Theme.of(context).colorScheme);
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return AirPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label.toUpperCase(), style: TextStyle(
            color: muted, fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: .7,
          )),
          const SizedBox(height: AirSpacing.xs),
          Text(value, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(
            color: color, fontSize: 22, fontWeight: FontWeight.w800,
            fontFeatures: const [FontFeature.tabularFigures()],
          )),
          if (caption != null) ...[
            const SizedBox(height: AirSpacing.xxs),
            Text(caption!, maxLines: 2, overflow: TextOverflow.ellipsis,
              style: TextStyle(color: muted, fontSize: 11)),
          ],
        ],
      ),
    );
  }
}

/// Semantic status pill. Text remains explicit so colour is never the only cue.
class AirStatusBadge extends StatelessWidget {
  const AirStatusBadge({
    super.key,
    required this.label,
    this.tone = AirStatusTone.neutral,
  });

  final String label;
  final AirStatusTone tone;

  @override
  Widget build(BuildContext context) {
    final color = switch (tone) {
      AirStatusTone.positive => AirPalette.positive,
      AirStatusTone.negative => AirPalette.negative,
      AirStatusTone.warning => AirPalette.warning,
      AirStatusTone.neutral => Theme.of(context).colorScheme.onSurfaceVariant,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(AirRadii.pill),
        border: Border.all(color: color.withValues(alpha: .28)),
      ),
      child: Text(label.toUpperCase(), style: TextStyle(
        color: color, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: .6,
      )),
    );
  }
}

class AirSectionHeader extends StatelessWidget {
  const AirSectionHeader({
    super.key,
    required this.title,
    this.trailing,
  });

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Expanded(child: Text(title.toUpperCase(), style: Theme.of(context).textTheme.labelLarge?.copyWith(
        fontWeight: FontWeight.w800, letterSpacing: .8,
      ))),
      if (trailing != null) trailing!,
    ],
  );
}

class AirEmptyState extends StatelessWidget {
  const AirEmptyState({
    super.key,
    required this.title,
    required this.message,
    this.icon = Icons.inbox_outlined,
  });

  final String title;
  final String message;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AirSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 34, color: muted),
            const SizedBox(height: AirSpacing.md),
            Text(title, textAlign: TextAlign.center,
              style: const TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: AirSpacing.xs),
            Text(message, textAlign: TextAlign.center,
              style: TextStyle(color: muted, fontSize: 12, height: 1.4)),
          ],
        ),
      ),
    );
  }
}
