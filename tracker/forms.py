from datetime import date

from django import forms

from .models import ACTIVITY_CHOICES


class ActivityForm(forms.Form):
    activity_type = forms.ChoiceField(choices=ACTIVITY_CHOICES, label="Aktivite Türü")
    date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Tarih",
        initial=date.today,
    )
    duration_minutes = forms.IntegerField(min_value=1, label="Süre (dakika)")
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Notlar",
    )
