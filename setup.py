from distutils.core import setup

setup(name='locker-support',
      version='10.4.7',
      author='Debathena Project',
      author_email='debathena@mit.edu',
      py_modules=['locker', 'athdir'],
      scripts=['attach', 'detach', 'fsid', 'quota.debathena', 'athdir'],
      )
