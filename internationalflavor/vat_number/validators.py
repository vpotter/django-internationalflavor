from __future__ import absolute_import
from __future__ import unicode_literals

import re
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils.translation import ugettext_lazy as _
from .data import VAT_NUMBER_REGEXES, EU_VAT_AREA


VIES_CHECK_WSDL = "http://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"


class VATNumberValidator(object):
    """Validator for checking whether a given VAT number is valid. A VAT number starts with two characters representing
    the country code, followed by at least 2 characters representing the local VAT number.

    :param bool eu_only: By default, all countries are allowed. However, if you are an EU company, you are likely to
        only want to accept EU VAT numbers.

    :param include_countries: If set, the list of countries will be limited to the provided list.

    :param bool vies_check: By default, this validator will only validate the syntax of the VAT number. If you need to
        validate using the EU VAT Information Exchange System (VIES) checker (see
        http://ec.europa.eu/taxation_customs/vies/), you can set this boolean. Any VAT number in the EU VAT Area will
        then receive additional validation from the VIES checker, other VAT numbers will be unaffected. This option
        requires the :mod:`suds` module to be installed. (You could use the ``suds-jurko`` fork for Py3k compatibility)

    .. note::

       If the VIES service can not be reached, this part of the validation will succeed.

    .. warning::

       The validation of non-EU VAT numbers may be incomplete or wrong in some cases. Please issue a pull request if you
       feel there's an error.

    The need for :mod:`suds` could (should) be removed in a future version of this package.
    """

    def __init__(self, eu_only=False, include_countries=None, vies_check=False):
        self.regexes = VAT_NUMBER_REGEXES
        self._suds_exception = None

        self.vies_check = vies_check
        if self.vies_check:
            try:
                import suds
            except ImportError:
                raise ImproperlyConfigured("The VAT VIES check requires the suds module to be installed.")
            else:
                del suds  # this suppresses some flake warnings

        self.included_countries = []
        if eu_only:
            self.included_countries += EU_VAT_AREA
        if include_countries is not None:
            self.included_countries += include_countries

    def __call__(self, value):
        """Validates whether a VAT number validates for a EU country."""
        if value is None:
            return value

        if not re.match(r"^[A-Z]{2}[A-Z0-9]+$", value):
            raise ValidationError(_('This VAT number does not start with a country code, or contains invalid '
                                    'characters.'))

        country = value[0:2]
        rest = value[2:]

        if self.included_countries and country not in self.included_countries:
            raise ValidationError(_('%(country)s VAT numbers are not allowed in this field.') % {'country': country})

        country_failure = _('This VAT number does not match the requirements for %(country)s.') % {'country': country}

        try:
            if not re.match(self.regexes[country], rest):
                raise ValidationError(country_failure)
        except KeyError:
            raise ValidationError(_('This VAT number is not for a known country.'))

        # Country specific checks
        if country == 'NL':  # validate against modified elfproef
            total = 0
            for i in range(8):
                total += int(rest[i]) * (9 - i)
            total -= int(rest[8])  # '1' factor is -1 in dutch test
            if total % 11 != 0:
                raise ValidationError(country_failure)

        elif country == 'BE':  # validate with Modulus97 test
            if (97 - (int(rest[0:8]) % 97)) != int(rest[8:10]):
                raise ValidationError(country_failure)

        # Check with WSDL services for valid VAT number
        if self.vies_check and country in EU_VAT_AREA:
            import suds
            import suds.client
            import suds.transport
            try:
                c = suds.client.Client(VIES_CHECK_WSDL, timeout=3)
                res = c.service.checkVat(country, rest)
                valid = res.valid is not False
            except (suds.WebFault, suds.transport.TransportError) as e:
                self._suds_exception = e
            else:
                if not valid:
                    raise ValidationError(_('This VAT number does not exist.'))
