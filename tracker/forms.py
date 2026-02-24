from django import forms

from .models import ACTIVITY_CHOICES, Player


class ActivityForm(forms.Form):
    activity_type = forms.ChoiceField(choices=ACTIVITY_CHOICES, label="Aktivite Türü")
    duration_minutes = forms.IntegerField(min_value=1, required=False, label="Süre (dakika)")
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Notlar",
    )


class PlayerSignupForm(forms.Form):
    name = forms.CharField(max_length=100, label="Ad Soyad")

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Lütfen bir isim gir.")
        if Player.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("Bu isim zaten kayıtlı. Lütfen giriş yap veya farklı bir isim dene.")
        return name
