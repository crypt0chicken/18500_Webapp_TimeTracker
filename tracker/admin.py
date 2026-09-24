from django.contrib import admin
from .models import (
    Team,
    SwimmerProfile,
    PersonalBest,
    HardwareTag,
    PracticeSession,
    WorkoutSet,
    Repetition,
    LapSplit,
    SystemConfiguration,
)


@admin.register(SystemConfiguration)
class SystemConfigurationAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'allow_self_registration', 'team_leaderboard_visible', 'default_pool_course')

    def has_add_permission(self, request):
        # Prevent creating multiple configuration rows
        return not SystemConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class LapSplitInline(admin.TabularInline):
    model = LapSplit
    extra = 0
    readonly_fields = ('recorded_at',)


@admin.register(Repetition)
class RepetitionAdmin(admin.ModelAdmin):
    list_display = ('swimmer', 'workout_set', 'rep_number', 'total_time_seconds', 'effort_percentage')
    list_filter = ('workout_set__session', 'swimmer')
    inlines = [LapSplitInline]


class WorkoutSetInline(admin.TabularInline):
    model = WorkoutSet
    extra = 1


@admin.register(PracticeSession)
class PracticeSessionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'coach', 'pool_course', 'mode', 'status', 'created_at')
    list_filter = ('pool_course', 'mode', 'status', 'team')
    search_fields = ('team__name', 'coach__username')
    inlines = [WorkoutSetInline]


@admin.register(HardwareTag)
class HardwareTagAdmin(admin.ModelAdmin):
    list_display = ('tag_id', 'battery_percentage', 'active_swimmer', 'firmware_version', 'last_seen')
    list_filter = ('battery_percentage',)
    search_fields = ('tag_id', 'active_swimmer__user__username')
    actions = ['unassign_selected_tags']

    @admin.action(description="Unassign selected tags from swimmers")
    def unassign_selected_tags(self, request, queryset):
        updated = queryset.update(active_swimmer=None)
        self.message_user(request, f"{updated} tag(s) successfully unassigned.")


admin.site.register(Team)
admin.site.register(SwimmerProfile)
admin.site.register(PersonalBest)