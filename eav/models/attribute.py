# ruff: noqa: UP007

from typing import TYPE_CHECKING, Optional, Tuple  # noqa: UP035

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ForeignKey
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from eav.fields import EavDatatypeField
from eav.logic.entity_pk import get_entity_pk_type
from eav.logic.managers import AttributeManager
from eav.logic.object_pk import get_pk_format
from eav.logic.slug import SLUGFIELD_MAX_LENGTH, generate_slug
from eav.settings import CHARFIELD_LENGTH
from eav.validators import (
    validate_bool,
    validate_csv,
    validate_date,
    validate_enum,
    validate_float,
    validate_int,
    validate_json,
    validate_object,
    validate_text,
)

from .enum_value import EnumValue
from .value import Value

if TYPE_CHECKING:
    from .enum_group import EnumGroup


class Attribute(models.Model):
    """
    Putting the **A** in *EAV*. This holds the attributes, or concepts.
    Examples of possible *Attributes*: color, height, weight, number of
    children, number of patients, has fever?, etc...

    Each attribute has a name, and a description, along with a slug that must
    be unique.  If you don't provide a slug, a default slug (derived from
    name), will be created.

    The *required* field is a boolean that indicates whether this EAV attribute
    is required for entities to which it applies. It defaults to *False*.

    .. warning::
       Just like a normal model field that is required, you will not be able
       to save or create any entity object for which this attribute applies,
       without first setting this EAV attribute.

    There are 7 possible values for datatype:

        * int (TYPE_INT)
        * float (TYPE_FLOAT)
        * text (TYPE_TEXT)
        * date (TYPE_DATE)
        * bool (TYPE_BOOLEAN)
        * object (TYPE_OBJECT)
        * enum (TYPE_ENUM)
        * json (TYPE_JSON)
        * csv (TYPE_CSV)


    Examples::

        Attribute.objects.create(name='Height', datatype=Attribute.TYPE_INT)
        # = <Attribute: Height (Integer)>

        Attribute.objects.create(name='Color', datatype=Attribute.TYPE_TEXT)
        # = <Attribute: Color (Text)>

        yes = EnumValue.objects.create(value='yes')
        no = EnumValue.objects.create(value='no')
        unknown = EnumValue.objects.create(value='unknown')
        ynu = EnumGroup.objects.create(name='Yes / No / Unknown')
        ynu.values.add(yes, no, unknown)

        Attribute.objects.create(name='has fever?', datatype=Attribute.TYPE_ENUM, enum_group=ynu)
        # = <Attribute: has fever? (Multiple Choice)>

    .. warning:: Once an Attribute has been used by an entity, you can not
                 change it's datatype.
    """

    objects = AttributeManager()

    class Meta:
        ordering = ['name']
        verbose_name = _('Attribute')
        verbose_name_plural = _('Attributes')

    TYPE_TEXT = 'text'
    TYPE_FLOAT = 'float'
    TYPE_INT = 'int'
    TYPE_DATE = 'date'
    TYPE_BOOLEAN = 'bool'
    TYPE_OBJECT = 'object'
    TYPE_ENUM = 'enum'
    TYPE_JSON = 'json'
    TYPE_CSV = 'csv'

    DATATYPE_CHOICES = (
        (TYPE_TEXT, _('Text')),
        (TYPE_DATE, _('Date')),
        (TYPE_FLOAT, _('Float')),
        (TYPE_INT, _('Integer')),
        (TYPE_BOOLEAN, _('True / False')),
        (TYPE_OBJECT, _('Django Object')),
        (TYPE_ENUM, _('Multiple Choice')),
        (TYPE_JSON, _('JSON Object')),
        (TYPE_CSV, _('Comma-Separated-Value')),
    )

    # Core attributes
    id = get_pk_format()

    datatype = EavDatatypeField(
        choices=DATATYPE_CHOICES,
        max_length=6,
        verbose_name=_('Data Type'),
    )

    name = models.CharField(
        max_length=CHARFIELD_LENGTH,
        help_text=_('User-friendly attribute name'),
        verbose_name=_('Name'),
    )

    """
    Main identifer for the attribute.
    Upon creation, slug is autogenerated from the name.
    (see :meth:`~eav.fields.EavSlugField.create_slug_from_name`).
    """
    slug = models.SlugField(
        max_length=SLUGFIELD_MAX_LENGTH,
        db_index=True,
        unique=True,
        help_text=_('Short unique attribute label'),
        verbose_name=_('Slug'),
    )

    """
    .. warning::
        This attribute should be used with caution. Setting this to *True*
        means that *all* entities that *can* have this attribute will
        be required to have a value for it.
    """
    required = models.BooleanField(
        default=False,
        verbose_name=_('Required'),
    )

    entity_ct = models.ManyToManyField(
        ContentType,
        blank=True,
        verbose_name=_('Entity content type'),
    )
    """
    This field allows you to specify a relationship with any number of content types.
    This would be useful, for example, if you wanted an attribute to apply only to
    a subset of entities. In that case, you could filter by content type in the
    :meth:`~eav.registry.EavConfig.get_attributes` method of that entity's config.
    """

    enum_group: "ForeignKey[Optional[EnumGroup]]" = ForeignKey(
        "eav.EnumGroup",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        verbose_name=_('Choice Group'),
    )

    description = models.CharField(
        max_length=256,
        blank=True,
        null=True,
        help_text=_('Short description'),
        verbose_name=_('Description'),
    )

    # Useful meta-information

    display_order = models.PositiveIntegerField(
        default=1,
        verbose_name=_('Display order'),
    )

    modified = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Modified'),
    )

    created = models.DateTimeField(
        default=timezone.now,
        editable=False,
        verbose_name=_('Created'),
    )

    def __str__(self) -> str:
        return f'{self.name} ({self.get_datatype_display()})'

    def natural_key(self) -> Tuple[str, str]:  # noqa: UP006
        """
        Retrieve the natural key for the Attribute instance.

        The natural key for an Attribute is defined by its `name` and `slug`. This method
        returns a tuple containing these two attributes of the instance.

        Returns
        -------
            tuple: A tuple containing the name and slug of the Attribute instance.
        """
        return (
            self.name,
            self.slug,
        )

    @property
    def help_text(self):
        return self.description

    def get_validators(self):
        """
        Returns the appropriate validator function from :mod:`~eav.validators`
        as a list (of length one) for the datatype.

        .. note::
           The reason it returns it as a list, is eventually we may want this
           method to look elsewhere for additional attribute specific
           validators to return as well as the default, built-in one.
        """
        DATATYPE_VALIDATORS = {
            'text': validate_text,
            'float': validate_float,
            'int': validate_int,
            'date': validate_date,
            'bool': validate_bool,
            'object': validate_object,
            'enum': validate_enum,
            'json': validate_json,
            'csv': validate_csv,
        }

        return [DATATYPE_VALIDATORS[self.datatype]]

    def validate_value(self, value):
        """
        Check *value* against the validators returned by
        :meth:`get_validators` for this attribute.
        """
        for validator in self.get_validators():
            validator(value)

        if self.datatype == self.TYPE_ENUM:
            if isinstance(value, EnumValue):
                value = value.value
            if not self.enum_group.values.filter(value=value).exists():
                raise ValidationError(
                    _('%(val)s is not a valid choice for %(attr)s')
                    % {'val': value, 'attr': self},
                )

    def save(self, *args, **kwargs):
        """
        Saves the Attribute and auto-generates a slug field
        if one wasn't provided.
        """
        if not self.slug:
            self.slug = generate_slug(self.name)

        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        """
        Validates the attribute.  Will raise ``ValidationError`` if the
        attribute's datatype is *TYPE_ENUM* and enum_group is not set, or if
        the attribute is not *TYPE_ENUM* and the enum group is set.
        """
        if self.datatype == self.TYPE_ENUM and not self.enum_group:
            raise ValidationError(
                _('You must set the choice group for multiple choice attributes'),
            )

        if self.datatype != self.TYPE_ENUM and self.enum_group:
            raise ValidationError(
                _('You can only assign a choice group to multiple choice attributes'),
            )

    def get_choices(self):
        """
        Returns a query set of :class:`EnumValue` objects for this attribute.
        Returns None if the datatype of this attribute is not *TYPE_ENUM*.
        """
        return (
            self.enum_group.values.all()
            if self.datatype == Attribute.TYPE_ENUM
            else None
        )

    def save_value(self, entity, value):
        """
        Called with *entity*, any Django object registered with eav, and
        *value*, the :class:`Value` this attribute for *entity* should
        be set to.

        If a :class:`Value` object for this *entity* and attribute doesn't
        exist, one will be created.

        .. note::
           If *value* is None and a :class:`Value` object exists for this
           Attribute and *entity*, it will delete that :class:`Value` object.
        """
        ct = ContentType.objects.get_for_model(entity)

        entity_filter = {
            'entity_ct': ct,
            'attribute': self,
            f'{get_entity_pk_type(entity)}': entity.pk,
        }

        try:
            value_obj = self.value_set.get(**entity_filter)
        except Value.DoesNotExist:
            if value is None or value == '':
                return

            value_obj = Value.objects.create(**entity_filter)

        if value is None or value == '':
            value_obj.delete()
            return

        if value != value_obj.value:
            value_obj.value = value
            value_obj.save()
