Name:		athenora-locker-support
Version:	10.4.7
Release:	1%{?dist}
Summary:	Python modules for Athena\'s "locker" framework

Group:		Applications/System
License:	BSD
URL:		https://github.com/mit-athena/locker-support/
Source0:	https://debathena.mit.edu/redist/locker-support-%{version}.tar.gz

BuildArch:	noarch

BuildRequires:	python-setuptools
BuildRequires:	python2-devel

Requires:	python-afs
Requires:	python-hesiod

%description
This package provides the "locker" and "athdir" modules, for use with
athenora-pyhesiodfs and more

%package -n athenora-attach
Summary:	Athena utility to attach a remote file system to the workstation

Requires:   	athenora-locker-support

%description -n athenora-attach
The attach utility is a filesystem-independent utility which allows
you to attach a filesystem to a directory hierarchy on a workstation.
Currently supported filesystem types are AFS, NFS, and UFS.

%package -n athenora-athdir
Summary:	Utility to find machine-specific directories using Athena conventions

Requires:	athenora-locker-support

%description -n athenora-athdir
The athdir utility is used to locate specific types of files in an
Athena locker.  It knows about all the conventions for compatibility
with older operating system versions and processor types, and is the
preferred way to determine the correct directory in a locker in which
to find binaries or other architecture-dependent files.

%package -n athenora-quota
Summary:	Print disk usage and quota limits

%description -n athenora-quota
Quota displays a user's disk usage and limits on local and NFS mounted
file systems, as well as AFS lockers that have been attached. If a
user is specified (by name or by id), quota will return information on
disk usage and limits for that user. Normal users can only check their
own quotas. The super-user may check any quota on local filesystems.

%prep
%setup -q -n locker-support-%{version}

%build
CFLAGS="$RPM_OPT_FLAGS" CPPFLAGS="-I%{_includedir}/et" %{__python2} setup.py build

%install
rm -rf $RPM_BUILD_ROOT
%{__python2} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT
mkdir -p %{buildroot}%{_mandir}/man1/
cp -v man/*.1 %{buildroot}%{_mandir}/man1/
ln -s /bin/true %{buildroot}/usr/bin/zinit
ln -s /bin/true %{buildroot}/usr/bin/nfsid

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%doc
%{python_sitelib}/*

%files -n athenora-attach
/usr/bin/attach
/usr/bin/detach
/usr/bin/fsid
/usr/bin/nfsid
/usr/bin/zinit
%doc %{_mandir}/man1/add.1.gz
%doc %{_mandir}/man1/attach.1.gz
%doc %{_mandir}/man1/detach.1.gz
%doc %{_mandir}/man1/fsid.1.gz

%files -n athenora-athdir
/usr/bin/athdir
%doc %{_mandir}/man1/athdir.1.gz

%files -n athenora-quota
/usr/bin/quota.debathena
%doc %{_mandir}/man1/quota.debathena.1.gz

%changelog
* Wed Aug  6 2014 Alex Chernyakhovsky <achernya@mit.edu> - 10.4.7-1
- Initial packaging.
